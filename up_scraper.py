#!/usr/bin/env python3
import sys
import re
import json
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

MAPPA_GIORNI = {
    "lun": "Lunedì",
    "mar": "Martedì",
    "mer": "Mercoledì",
    "gio": "Giovedì",
    "ven": "Venerdì",
    "sab": "Sabato",
    "dom": "Domenica"
}

def analizza_titolo_poliba(titolo_raw: str):
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

def estrai_singolo_evento(ev_dom, giorno: str, meta: dict):
    testo = ev_dom.get_text(separator="\n").strip()
    righe = [r.strip() for r in testo.split("\n") if r.strip()]

    ora_inizio, ora_fine = None, None
    if righe:
        m_ora = re.search(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", righe[0])
        if m_ora:
            ora_inizio = m_ora.group(1)
            ora_fine = m_ora.group(2)
        else:
            return None

    insegnamento = ""
    for r in righe[1:]:
        if not re.search(r"^(Iniziali|Aula|Prof|Dott)", r, re.IGNORECASE) and not re.search(r"^[A-Z]-[A-Z]$", r):
            insegnamento = r
            break

    aula = "N/D"
    partizione = meta["partizione"]

    for riga in righe:
        m_a = re.search(r"Aula\s+([A-Za-z0-9_\-\.]+)", riga, re.IGNORECASE)
        if m_a:
            aula = f"Aula {m_a.group(1)}"
        m_p = re.search(r"(?:Iniziali\s+cognome\s+|Partizione\s+)([A-Z]-[A-Z])", riga, re.IGNORECASE)
        if m_p:
            partizione = m_p.group(1)

    return {
        "aula": normalizza_nome_aula(aula),
        "giorno": giorno,
        "orario_inizio": ora_inizio,
        "orario_fine": ora_fine,
        "corso_di_studio": meta["corso_di_studio"],
        "anno_corso": meta["anno_corso"],
        "eventuale_percorso": meta["percorso"],
        "partizione": partizione,
        "nome_insegnamento": insegnamento
    }

def parse_fullcalendar_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    titolo_el = soup.find(id="titoloCalendarioPubblico")
    titolo = titolo_el.get_text(strip=True) if titolo_el else ""
    meta = analizza_titolo_poliba(titolo)

    # 1. Recupero ordine dei giorni dall'header di FullCalendar
    cols_header = soup.select(".fc-head .fc-day-header")
    col_names = []
    for ch in cols_header:
        testo = ch.get_text(strip=True).lower()
        nome = None
        for sigla, esteso in MAPPA_GIORNI.items():
            if sigla in testo:
                nome = esteso
                break
        col_names.append(nome if nome else ch.get_text(strip=True))

    lezioni = []

    # 2. Ogni giorno ha una colonna td nella tabella fc-content-skeleton
    colonne = soup.select(".fc-time-grid .fc-content-skeleton td:not(.fc-axis)")

    if colonne and len(colonne) == len(col_names):
        # Mappatura 1:1 rigorosa della colonna DOM col giorno
        for idx, col in enumerate(colonne):
            giorno_corrente = col_names[idx]
            for ev in col.select(".fc-event, .fc-time-grid-event"):
                item = estrai_singolo_evento(ev, giorno_corrente, meta)
                if item and item["orario_inizio"] and item["orario_fine"]:
                    lezioni.append(item)
    else:
        # Se la struttura è flessibile, cerca i container per colonna
        event_containers = soup.select(".fc-time-grid .fc-content-skeleton .fc-event-container")
        if event_containers and len(event_containers) == len(col_names):
            for idx, container in enumerate(event_containers):
                giorno_corrente = col_names[idx]
                for ev in container.select(".fc-event, .fc-time-grid-event"):
                    item = estrai_singolo_evento(ev, giorno_corrente, meta)
                    if item and item["orario_inizio"] and item["orario_fine"]:
                        lezioni.append(item)

    return lezioni

def scrape_link(url: str, browser_context=None):
    def _execute(ctx):
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=40000)
        try:
            page.wait_for_selector(".fc-event, .fc-time-grid-event", timeout=12000)
        except Exception:
            pass
        html = page.content()
        page.close()
        return parse_fullcalendar_html(html)

    if browser_context:
        return _execute(browser_context)
    else:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(viewport={"width": 1920, "height": 1080})
            risultati = _execute(ctx)
            b.close()
            return risultati

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Errore: specificare l'URL del calendario come parametro.", file=sys.stderr)
        print("Esempio: python up_scraper.py \"https://poliba.prod.up.cineca.it/calendarioPubblico/linkCalendarioId=...\"", file=sys.stderr)
        sys.exit(1)

    target_url = sys.argv[1].strip()
    risultati = scrape_link(target_url)
    print(json.dumps(risultati, indent=2, ensure_ascii=False))