#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright
import up_scraper

# Fasce standard richieste
ORA_INIZIO_DEFAULT = "08:30"
ORA_FINE_DEFAULT = "20:00"
GIORNI_DEFAULT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato"]


def to_minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def to_hhmm(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def popola_archivio_da_grezzo(
    raw_path="orari_scraped.json", archive_path="up_archive.json"
):
    """Legge il file grezzo di scraping, filtra PDF e Drive esterni (ArCoD),
    normalizza gli URL, deduplica i calendari identici e salva up_archive.json.
    """
    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"File grezzo '{raw_path}' non trovato.")

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Controllo di sicurezza: intercetta errori 404 di GitHub
    if isinstance(raw_data, dict) and raw_data.get("status") == "404":
        raise RuntimeError(
            f"ERRORE: '{raw_path}' contiene una risposta 404 dalle API GitHub.\n"
            "Verifica che il secret UDU_HUB_TOKEN sia valido e che il repository sia 'UDUBari/udubari-website'."
        )

    # Dizionario con chiave = linkCalendarioId per deduplicare
    unique_links = {}

    for dipartimento, lista_corsi in raw_data.items():
        if not isinstance(lista_corsi, list):
            continue

        for item in lista_corsi:
            url_raw = item.get("link", "").strip()

            # 1. Ignora PDF, Google Drive (ArCoD) o link che non appartengono a UP Cineca
            if (
                not url_raw
                or item.get("isDirect") is True
                or ".pdf" in url_raw.lower()
                or "drive.google.com" in url_raw.lower()
                or "cineca.it" not in url_raw
            ):
                continue

            # 2. Estrai il linkCalendarioId univoco
            match_id = re.search(r"linkCalendarioId=([a-f0-9]+)", url_raw)
            if not match_id:
                continue

            link_id = match_id.group(1)
            url_pulito = (
                f"https://poliba.prod.up.cineca.it/calendarioPubblico/linkCalendarioId={link_id}"
            )

            # Etichetta leggibile e pulita
            nome_corso = item.get("name", "").strip()
            anno_pulito = item.get("yearClean") or item.get("year", "")
            anno_pulito = re.sub(r"&#176;", "°", str(anno_pulito)).strip()
            label = f"[{dipartimento}] {nome_corso} ({anno_pulito})"

            if link_id not in unique_links:
                unique_links[link_id] = {
                    "link_id": link_id,
                    "url": url_pulito,
                    "dipartimenti": [dipartimento],
                    "descrizioni": [label],
                }
            else:
                if dipartimento not in unique_links[link_id]["dipartimenti"]:
                    unique_links[link_id]["dipartimenti"].append(dipartimento)
                if label not in unique_links[link_id]["descrizioni"]:
                    unique_links[link_id]["descrizioni"].append(label)

    # Costruisci l'archivio strutturato
    archive_payload = {
        "generato_il": datetime.now().isoformat(),
        "config": {
            "ora_inizio_giornata": ORA_INIZIO_DEFAULT,
            "ora_fine_giornata": ORA_FINE_DEFAULT,
            "giorni_lavorativi": GIORNI_DEFAULT,
        },
        "links": [
            {
                "link_id": v["link_id"],
                "descrizione": " / ".join(v["descrizioni"]),
                "dipartimento": ", ".join(v["dipartimenti"]),
                "url": v["url"],
            }
            for v in unique_links.values()
        ],
    }

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive_payload, f, indent=2, ensure_ascii=False)

    print(
        f"[OK] Archivio '{archive_path}' popolato con successo: "
        f"{len(archive_payload['links'])} calendari Cineca UP univoci estratti."
    )
    return archive_payload


def calcola_fasce_libere(lezioni, ora_inizio_day="08:30", ora_fine_day="20:00"):
    """Fonde gli intervalli occupati e calcola le finestre di disponibilità libera."""
    start_day = to_minutes(ora_inizio_day)
    end_day = to_minutes(ora_fine_day)

    if not lezioni:
        return [
            {
                "orario_inizio": ora_inizio_day,
                "orario_fine": ora_fine_day,
                "durata_minuti": end_day - start_day,
            }
        ]

    # 1. Merge intervalli occupati
    occupati = []
    for lz in sorted(lezioni, key=lambda x: to_minutes(x["orario_inizio"])):
        s = max(to_minutes(lz["orario_inizio"]), start_day)
        e = min(to_minutes(lz["orario_fine"]), end_day)
        if s >= e:
            continue
        if not occupati:
            occupati.append([s, e])
        else:
            if s <= occupati[-1][1]:
                occupati[-1][1] = max(occupati[-1][1], e)
            else:
                occupati.append([s, e])

    # 2. Calcolo buchi liberi
    fasce_libere = []
    curr = start_day
    for occ_s, occ_e in occupati:
        if occ_s > curr:
            fasce_libere.append(
                {
                    "orario_inizio": to_hhmm(curr),
                    "orario_fine": to_hhmm(occ_s),
                    "durata_minuti": occ_s - curr,
                }
            )
        curr = max(curr, occ_e)

    if curr < end_day:
        fasce_libere.append(
            {
                "orario_inizio": to_hhmm(curr),
                "orario_fine": to_hhmm(end_day),
                "durata_minuti": end_day - curr,
            }
        )

    return fasce_libere


def build_aggregated_db(
    raw_path="orari_scraped.json",
    archive_path="up_archive.json",
    output_db="up_rooms_db.json",
):
    print("[FASE 1] Ingestione e normalizzazione da file grezzo...")
    archivio = popola_archivio_da_grezzo(raw_path, archive_path)

    cfg = archivio.get("config", {})
    ora_inizio_day = cfg.get("ora_inizio_giornata", ORA_INIZIO_DEFAULT)
    ora_fine_day = cfg.get("ora_fine_giornata", ORA_FINE_DEFAULT)
    giorni_lavorativi = cfg.get("giorni_lavorativi", GIORNI_DEFAULT)
    links = archivio.get("links", [])

    print(
        f"\n[FASE 2] Avvio scraping di {len(links)} link Cineca UP con Chromium..."
    )
    tutte_lezioni = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})

        for i, item in enumerate(links, 1):
            url = item["url"]
            desc = item.get("descrizione", url)
            print(f"[{i}/{len(links)}] Scraping: {desc[:75]}...")
            try:
                lezioni_link = up_scraper.scrape_link(url, browser_context=context)
                print(f"       └─ Estratte {len(lezioni_link)} lezioni")
                tutte_lezioni.extend(lezioni_link)
            except Exception as e:
                print(f"       [!] Errore durante lo scraping: {e}", file=sys.stderr)

        browser.close()

    print(
        f"\n[FASE 3] Aggregazione di {len(tutte_lezioni)} impegni complessivi..."
    )
    aule_db = {}

    for lz in tutte_lezioni:
        aula = lz["aula"]
        giorno = lz["giorno"]

        if (
            not aula
            or aula == "N/D"
            or not giorno
            or giorno not in giorni_lavorativi
        ):
            continue

        if aula not in aule_db:
            aule_db[aula] = {
                g: {"lezioni": [], "fasce_libere": []} for g in giorni_lavorativi
            }

        gia_presente = any(
            x["orario_inizio"] == lz["orario_inizio"]
            and x["orario_fine"] == lz["orario_fine"]
            and x["nome_insegnamento"] == lz["nome_insegnamento"]
            for x in aule_db[aula][giorno]["lezioni"]
        )
        if not gia_presente:
            aule_db[aula][giorno]["lezioni"].append(
                {
                    "orario_inizio": lz["orario_inizio"],
                    "orario_fine": lz["orario_fine"],
                    "nome_insegnamento": lz["nome_insegnamento"],
                    "corso_di_studio": lz["corso_di_studio"],
                    "anno_corso": lz["anno_corso"],
                    "eventuale_percorso": lz["eventuale_percorso"],
                    "partizione": lz["partizione"],
                }
            )

    for aula in aule_db:
        for giorno in aule_db[aula]:
            lezioni_ord = sorted(
                aule_db[aula][giorno]["lezioni"],
                key=lambda x: to_minutes(x["orario_inizio"]),
            )
            aule_db[aula][giorno]["lezioni"] = lezioni_ord
            aule_db[aula][giorno]["fasce_libere"] = calcola_fasce_libere(
                lezioni_ord, ora_inizio_day, ora_fine_day
            )

    database_finale = {
        "metadata": {
            "generato_il": datetime.now().isoformat(),
            "fascia_giornaliera": f"{ora_inizio_day} - {ora_fine_day}",
            "totale_aule": len(aule_db),
            "totale_corsi_elaborati": len(links),
        },
        "aule": aule_db,
    }

    with open(output_db, "w", encoding="utf-8") as f:
        json.dump(database_finale, f, indent=2, ensure_ascii=False)

    print(
        f"\n[SUCCESSO] Database aule '{output_db}' generato con successo!"
        f" ({len(aule_db)} aule mappate in fascia {ora_inizio_day}-{ora_fine_day})"
    )


if __name__ == "__main__":
    raw_file = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "orari_scraped.json"
    )
    build_aggregated_db(raw_path=raw_file)