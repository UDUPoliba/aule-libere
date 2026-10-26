#!/usr/bin/env python3
import json
import re
import html
import os
from pathlib import Path
import requests

POLIBA_URL = "https://www.poliba.it/it/orari-delle-lezioni"

# Percorsi calcolati rispetto alla radice del repository
ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_JSON = ROOT_DIR / "orari_scraped.json"
OUTPUT_TS = ROOT_DIR / "apps" / "web" / "src" / "pages" / "Poliba" / "components" / "polibaTimetableData.ts"

# Link manuali/Drive per ArCoD (aggiornabili qui quando cambiano a inizio semestre)
ARCOD_DATA = [
    {
        "code": "ARCOD_ARC",
        "name": "LM CICLO UNICO ARCHITETTURA",
        "year": "Tutti gli anni",
        "yearClean": "Orario Completo",
        "semester": "1S",
        "link": "https://drive.google.com/file/d/1r1t0JyY7wsLx_byCWB9RAqM018DysTG7/view?usp=sharing",
        "isDirect": True
    },
    {
        "code": "ARCOD_DES",
        "name": "LT DESIGN",
        "year": "Tutti gli anni",
        "yearClean": "Orario Completo",
        "semester": "1S",
        "link": "https://drive.google.com/file/d/1jFWhkNBi4SKQCeGEZqcZEDg8s2gnCfBI/view?usp=sharing",
        "isDirect": True
    }
]

def clean_text(text: str) -> str:
    if not text:
        return ""
    decoded = html.unescape(text)
    decoded = decoded.replace("&#176;", "°").replace("&#224;", "à").replace("&agrave;", "à")
    return re.sub(r"\s+", " ", decoded).strip()

def normalize_link(link: str) -> str:
    if not link:
        return ""
    return re.sub(r"([^:])//+", r"\1/", link.strip())

def extract_year_clean(year_str: str) -> str:
    y = clean_text(year_str)
    y_clean = y.replace("°", "").replace("-", " ")
    return re.sub(r"\s+", " ", y_clean).strip()

def main():
    print(f"[*] Connessione a {POLIBA_URL}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    resp = requests.get(POLIBA_URL, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Errore HTTP {resp.status_code} scaricando la pagina Poliba.")

    html_content = resp.text

    match = re.search(r"const\s+data\s*=\s*(\{[\s\S]*?\n\s*\});", html_content)
    if not match:
        raise ValueError("Impossibile trovare il blocco 'const data' nel sorgente della pagina.")

    js_obj_str = match.group(1)

    # 1. Rimuove commenti multiriga /* ... */
    js_obj_str = re.sub(r"/\*[\s\S]*?\*/", "", js_obj_str)

    # 2. Rimuove SOLO i commenti // a inizio riga
    js_obj_str = re.sub(r"^\s*//.*$", "", js_obj_str, flags=re.MULTILINE)

    # 3. Rimuove trailing commas
    js_obj_str = re.sub(r",\s*([\]}])", r"\1", js_obj_str)

    try:
        raw_dict = json.loads(js_obj_str)
    except json.JSONDecodeError:
        js_obj_str = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', js_obj_str)
        raw_dict = json.loads(js_obj_str)

    cleaned_dict = {}

    for dipartimento, corsi in raw_dict.items():
        dept_name = clean_text(dipartimento)
        if "TARANTO" in dept_name.upper():
            dept_name = "TARANTO"

        cleaned_dict[dept_name] = []
        for item in corsi:
            nome_pulito = clean_text(item.get("name", ""))
            anno_raw = clean_text(item.get("year", ""))

            cleaned_dict[dept_name].append({
                "code": item.get("code", "").strip(),
                "name": nome_pulito,
                "year": anno_raw,
                "yearClean": extract_year_clean(anno_raw),
                "semester": item.get("semester", "1S").strip(),
                "link": normalize_link(item.get("link", ""))
            })

    # Integrazione ArCoD
    cleaned_dict["ArCoD"] = ARCOD_DATA

    # 1. Scrittura orari_scraped.json nella root del repo
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(cleaned_dict, f, indent=4, ensure_ascii=False)
    print(f"[OK] Generato '{OUTPUT_JSON}' con successo.")

    # 2. Scrittura polibaTimetableData.ts con import corretto a '../../polibaTypes'
    OUTPUT_TS.parent.mkdir(parents=True, exist_ok=True)
    ts_code = "import type { DepartmentTimetableMap } from '../polibaTypes'\n\n"
    ts_code += "// File generato automaticamente via scripts/scrape_poliba_orari.py da poliba.it\n"
    ts_code += "export const polibaTimetableData: DepartmentTimetableMap = "
    ts_code += json.dumps(cleaned_dict, indent=4, ensure_ascii=False)
    ts_code += "\n"

    with open(OUTPUT_TS, "w", encoding="utf-8") as f:
        f.write(ts_code)
    print(f"[OK] Generato '{OUTPUT_TS}' con successo.")

if __name__ == "__main__":
    main()