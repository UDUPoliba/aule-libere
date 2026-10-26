#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

MAPPA_GIORNI_TEMPLATE = {
    1: "Lunedì",
    2: "Martedì",
    3: "Mercoledì",
    4: "Giovedì",
    5: "Venerdì",
    6: "Sabato",
    0: "Domenica",
    7: "Domenica"
}

ROME_TZ = ZoneInfo("Europe/Rome")


def iso_to_hhmm(iso_str: str) -> str:
    """Converte un timestamp ISO UTC nell'orario HH:MM nel fuso di Roma."""
    if not iso_str:
        return ""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    dt_local = dt.astimezone(ROME_TZ)
    return dt_local.strftime("%H:%M")


def estrai_meta_da_titolo(titolo_raw: str) -> dict:
    parti = [p.strip() for p in titolo_raw.split(" - ") if p.strip()]
    meta = {
        "semestre": None, "anno_corso": None, "tipo_laurea": None,
        "corso_di_studio": None, "percorso": None, "partizione": None
    }
    percorsi_extra = []
    for parte in parti:
        p_up = parte.upper()
        if re.match(r"^[A-Z]-[A-Z]$", parte) or "CANALE" in p_up:
            meta["partizione"] = parte
        elif "SEM" in p_up:
            meta["semestre"] = parte
        elif "ANNO" in p_up:
            meta["anno_corso"] = parte
        elif any(t in p_up for t in ["C. L.", "TRIENNALE", "MAGISTRALE", "CICLO UNICO", "LAUREA"]):
            meta["tipo_laurea"] = parte
        elif any(c in p_up for c in ["INGEGNERIA", "ARCHITETTURA", "DISEGNO", "COSTRUZIONI"]):
            meta["corso_di_studio"] = parte
        else:
            percorsi_extra.append(parte)

    if percorsi_extra:
        meta["percorso"] = " - ".join(percorsi_extra)
    return meta


def normalizza_nome_aula(aula_raw: str) -> str:
    if not aula_raw or aula_raw == "N/D":
        return "N/D"
    pulita = re.sub(r"\s+", " ", aula_raw).strip()
    match = re.search(r"Aula\s+([A-Za-z0-9_\-\.]+)", pulita, re.IGNORECASE)
    if match:
        return f"Aula {match.group(1).upper()}"
    return pulita


def estrai_lezioni_da_impegni_json(impegni: list, meta_calendario: dict) -> list:
    lezioni = []

    for imp in impegni:
        # 1. Recupero giorno della settimana
        giorno_idx = imp.get("giornoSettimanaTemplate")
        if giorno_idx is not None and giorno_idx in MAPPA_GIORNI_TEMPLATE:
            giorno = MAPPA_GIORNI_TEMPLATE[giorno_idx]
        else:
            data_inizio_iso = imp.get("dataInizio")
            if not data_inizio_iso:
                continue
            dt = datetime.fromisoformat(data_inizio_iso.replace("Z", "+00:00")).astimezone(ROME_TZ)
            giorno = MAPPA_GIORNI_TEMPLATE.get(dt.isoweekday() % 7, "Domenica")

        # 2. Orari normalizzati
        ora_inizio = iso_to_hhmm(imp.get("dataInizio"))
        ora_fine = iso_to_hhmm(imp.get("dataFine"))
        if not ora_inizio or not ora_fine:
            continue

        # 3. Metadati insegnamento / corso
        evento = imp.get("evento") or {}
        dettagli = evento.get("dettagliDidattici") or []
        primo_dettaglio = dettagli[0] if dettagli else {}

        nome_insegnamento = (
            imp.get("nome")
            or primo_dettaglio.get("nome")
            or primo_dettaglio.get("descrizione")
            or ""
        )

        corso_nome = (
            primo_dettaglio.get("corso", {}).get("descrizione")
            or meta_calendario.get("corso_di_studio")
        )
        anno_corso = primo_dettaglio.get("annoCorso") or meta_calendario.get("anno_corso")
        percorso = (
            primo_dettaglio.get("percorso", {}).get("descrizione")
            or meta_calendario.get("percorso")
        )
        partizione = primo_dettaglio.get("partizione") or meta_calendario.get("partizione")

        # 4. Raccoglie tutte le aule associate all'evento
        aule_candidate = []
        if imp.get("aule"):
            aule_candidate.extend(imp["aule"])
        if imp.get("risorse"):
            for r in imp["risorse"]:
                if r.get("aula"):
                    aule_candidate.append(r["aula"])

        # Deduplica per ID aula
        aule_uniche = {}
        for a in aule_candidate:
            a_id = a.get("id") or a.get("_id") or a.get("codice")
            if a_id and a_id not in aule_uniche:
                aule_uniche[a_id] = a

        for aula_obj in aule_uniche.values():
            edificio_obj = aula_obj.get("edificio") or {}
            comune = (edificio_obj.get("comune") or "").strip().upper()
            edificio_desc = (edificio_obj.get("descrizione") or "").strip().upper()
            cod_aula = (aula_obj.get("codice") or "").strip().upper()
            nome_aula_raw = aula_obj.get("descrizione") or cod_aula

            # --- FILTRO DETERMINISTICO TARANTO/TTEC DA API CINECA ---
            if (
                comune == "TARANTO"
                or "TTEC" in edificio_desc
                or "TARANTO" in edificio_desc
                or cod_aula.startswith("TA_")
                or cod_aula.startswith("TA-")
            ):
                continue

            aula_normalizzata = normalizza_nome_aula(nome_aula_raw)
            if not aula_normalizzata or aula_normalizzata == "N/D":
                continue

            lezioni.append({
                "aula": aula_normalizzata,
                "giorno": giorno,
                "orario_inizio": ora_inizio,
                "orario_fine": ora_fine,
                "corso_di_studio": corso_nome,
                "anno_corso": str(anno_corso) if anno_corso else None,
                "eventuale_percorso": percorso,
                "partizione": partizione,
                "nome_insegnamento": nome_insegnamento
            })

    return lezioni


def scrape_link(url: str, browser_context=None) -> list:
    def _execute(ctx):
        page = ctx.new_page()
        impegni_data = []
        titolo_calendario = ""

        def handle_response(response):
            nonlocal impegni_data, titolo_calendario
            if "searchCalendarioPubblico" in response.url:
                try:
                    res = response.json()
                    payload = res.get("payload") if isinstance(res, dict) else res
                    if isinstance(payload, dict) and payload.get("titolo"):
                        titolo_calendario = payload.get("titolo", "")
                except Exception:
                    pass

            elif "getImpegniCalendarioPubblico" in response.url:
                try:
                    res = response.json()
                    if isinstance(res, list):
                        impegni_data.extend(res)
                except Exception:
                    pass

        page.on("response", handle_response)
        page.goto(url, wait_until="networkidle", timeout=45000)

        # Attesa del caricamento effettivo dei dati prima di chiudere la pagina
        try:
            page.wait_for_selector(".fc-event, .fc-time-grid-event", timeout=12000)
        except Exception:
            pass

        page.close()

        meta = estrai_meta_da_titolo(titolo_calendario)
        return estrai_lezioni_da_impegni_json(impegni_data, meta)

    if browser_context:
        return _execute(browser_context)
    else:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(
                viewport={"width": 1920, "height": 1080},
                timezone_id="Europe/Rome",
                locale="it-IT"
            )
            risultati = _execute(ctx)
            b.close()
            return risultati


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Errore: specificare l'URL del calendario come parametro.", file=sys.stderr)
        sys.exit(1)

    target_url = sys.argv[1].strip()
    risultati = scrape_link(target_url)
    print(json.dumps(risultati, indent=2, ensure_ascii=False))