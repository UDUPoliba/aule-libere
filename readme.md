# Aule Libere PoliBa • UDU Politecnico di Bari

Applicazione web e pipeline di scraping automatizzata per la mappatura e la consultazione in tempo reale delle aule libere del **Campus di Bari (Campus Quagliariello / via Orabona)** del Politecnico di Bari.

Il sistema estrae gli orari ufficiali dai calendari accademici gestiti su **University Planner (Cineca UP)**, calcola gli slot orari privi di lezioni (fascia standard **08:30 – 20:00**) ed espone i risultati tramite un'interfaccia web responsive e serverless.

---

## 🏛️ Caratteristiche Principali

- **Scraping basato su API REST native**: Intercetta direttamente il traffico JSON scambiato dal client Angular di Cineca UP (`searchCalendarioPubblico` e `getImpegniCalendarioPubblico`), azzerando la fragilità del parsing DOM HTML.
- **Filtro geografico deterministico**: Esclusione automatica e robusta delle aule appartenenti al polo distaccato di Taranto (TTEC, DIASS, Magna Grecia) basata sui metadati reali dell'immobile (`aula.edificio.comune == "Taranto"`), indipendente dai nomi degli esami e resistente ai cambi di semestre.
- **Gestione Fuso Orario e Date UTC**: Conversione dei timestamp UTC dell'API nel fuso orario locale `Europe/Rome`, preservando la compatibilità con ora solare e ora legale.
- **Calcolo automatico fasce libere**: Algoritmo di unione intervalli occupati e complementazione rispetto alla fascia di apertura del campus per identificare con precisione tutti i buchi temporali.
- **Frontend Client-Side Zero-Backend**: Interfaccia visuale rapida, sviluppata in Vanilla JS, HTML5 e CSS3, con tre modalità di consultazione (Ricerca per Slot, Dettaglio per Singola Aula, Panoramica Giornaliera).

---

## 🏗️ Architettura del Sistema

```
                         [poliba.it/it/orari-delle-lezioni]
                                         │
                                         ▼
                             scrape_poliba_orari.py
                                         │
                                         ▼
                                 orari_scraped.json
                                         │
                                         ▼
                                  up_aggregator.py (Fase 1)
                                         │
                                         ▼
                                  up_archive.json
                                         │
                                         ▼
                            up_scraper.py (Playwright + API)
                                         │
                                         ▼
                                  up_aggregator.py (Fase 3)
                                         │
                                         ▼
                                  up_rooms_db.json
                                         │
                       ┌─────────────────┴─────────────────┐
                       ▼                                   ▼
                  index.html ◄───────────────────────── app.js
                  style.css
```

---

## 📁 Struttura dei File

| File | Descrizione |
|---|---|
| `scrape_poliba_orari.py` | Scarica la pagina degli orari di Ateneo, estrae l'oggetto JavaScript `const data` e genera l'albero grezzo `orari_scraped.json`. |
| `up_aggregator.py` | Coordina l'ingestione, la deduplicazione dei calendari, l'orchestrazione dello scraping con Playwright, la fusione degli impegni e il calcolo degli slot complementari liberi. |
| `up_scraper.py` | Modulo headless per singolo link Cineca: ascolta gli endpoint REST di Cineca UP ed estrae gli impegni normalizzati filtrando le aule non baresi. |
| `orari_scraped.json` | Mappa dipartimentale grezza di tutti i corsi, canali e link Cineca UP. |
| `up_archive.json` | Archivio deduplicato dei link Cineca canonici con relativi metadati di corso e partizione. |
| `up_rooms_db.json` | Database finale aggregato contenente il calendario settimanale delle lezioni e le fasce libere per ogni aula di Bari. |
| `index.html` | Layout applicativo con supporto responsive e tab navigation. |
| `style.css` | Stili grafici con palette istituzionale UDU (rosso/giallo) e tipografia Nunito Sans + Passion One. |
| `app.js` | Logica client-side di parsing, ricerca dinamica e rendering delle viste. |
| `requirements.txt` | Dipendenze Python necessarie per eseguire la pipeline. |

---

## ⚙️ Installazione e Requisiti

### Prerequisiti
- Python 3.10 o superiore
- Browser Chromium per Playwright

### Setup dell'ambiente

1. Clona il repository ed entra nella cartella di progetto:
   ```bash
   git clone <url-repo>
   cd up_scraper
   ```

2. Crea e attiva un ambiente virtuale Python:
   ```bash
   python3 -m venv venv
   source venv/bin/activate       # Su Linux/macOS
   # oppure: venv\Scripts\activate  # Su Windows
   ```

3. Installa le dipendenze:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

---

## 🚀 Esecuzione della Pipeline

### 1. (Opzionale) Aggiornamento link da Poliba
Se occorre riscaricare i link dei calendari pubblicati sul portale PoliBa:
```bash
python scrape_poliba_orari.py
```
Verrà aggiornato il file `orari_scraped.json`.

### 2. Generazione del Database Aule Libere
Avvia il processo di aggregazione e calcolo:
```bash
python up_aggregator.py
```
Il comando eseguirà in sequenza:
1. **Fase 1**: Deduplicazione dei calendari ed esclusione dei dipartimenti/corsi di Taranto (`up_archive.json`).
2. **Fase 2**: Apertura in background dei link con Playwright Chromium e intercettazione dei payload JSON da Cineca UP.
3. **Fase 3**: Aggregazione per aula, ordinamento orario, fusione lezioni sovrapposte e calcolo delle fasce libere nel file `up_rooms_db.json`.

### 3. Test di un Singolo Calendario
Per ispezionare il risultato su uno specifico link Cineca:
```bash
python up_scraper.py "https://poliba.prod.up.cineca.it/calendarioPubblico/linkCalendarioId=TUO_ID"
```

---

## 💻 Visualizzazione Frontend

L'applicazione non richiede server Node.js o backend dedicati. È sufficiente servire i file statici con un qualsiasi server HTTP:

```bash
# Esempio con modulo integrato Python:
python3 -m http.server 8080
```
Apri il browser all'indirizzo `http://localhost:8080`.

### Funzionalità dell'interfaccia:
- **Trova Aule Libere**: Seleziona giorno, orario di inizio e fine desiderati; il sistema mostra tutte le stanze con uno slot libero continuativo compatibile.
- **Dettaglio per Aula**: Permette di cercare qualsiasi aula per nome (es. `Aula AD`, `Aula Magna`, `Aula 10`) e visualizzare l'intero orario settimanale con lezioni e slot liberi.
- **Panoramica Giornaliera**: Mostra una tabella comparativa di tutte le aule del campus per un dato giorno, filtrabili per disponibilità minima (30m, 1h, 1h30, 2h).

---

## 🛡️ Gestione Polo di Taranto (TTEC / DIASS)

Le lezioni di Taranto che compaiono nei calendari condivisi (ad esempio per Civile e Ambientale o Aerospaziale) vengono eliminate in modo robusto attraverso criteri multilivello:

1. **A livello di link (`up_aggregator.py`)**: scarto dei dipartimenti e corsi con marcatore `"TARANTO"`.
2. **A livello di payload API Cineca (`up_scraper.py`)**:
   - `aula.edificio.comune == "Taranto"`
   - `aula.edificio.descrizione` contiene `"TTEC"` o `"TARANTO"`
   - `aula.codice` con prefisso `"TA_"` o `"TA-"`

Questo garantisce l'assoluta pulizia del database senza richiedere l'inserimento manuale di liste di docenti o insegnamenti specifici.