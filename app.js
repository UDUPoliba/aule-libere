let DATABASE = null;

const toMin = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

async function initApp() {
  try {
    const res = await fetch("up_rooms_db.json");
    if (!res.ok) throw new Error("File up_rooms_db.json non trovato.");
    DATABASE = await res.json();

    const meta = DATABASE.metadata || {};
    const count = meta.totale_aule || Object.keys(DATABASE.aule).length;
    document.getElementById("db-badge").innerText = 
      `${count} AULE MAPPATE • 08:30 - 20:00`;

    const giorniSettimana = ["Domenica", "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato"];
    const oggi = giorniSettimana[new Date().getDay()];
    if (["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato"].includes(oggi)) {
      document.getElementById("slot-giorno").value = oggi;
      document.getElementById("panoramica-giorno").value = oggi;
    }

    cercaAuleLibere();
  } catch (err) {
    const badge = document.getElementById("db-badge");
    badge.style.backgroundColor = "rgba(79, 1, 1, 0.8)";
    badge.style.color = "#ffffff";
    badge.innerText = "Errore caricamento database";
    console.error(err);
  }
}

function cambiaVista(vista) {
  ["slot", "aule", "giorno"].forEach(v => {
    document.getElementById(`vista-${v}`).classList.add("hidden");
    document.getElementById(`tab-btn-${v}`).classList.remove("active-tab");
  });

  document.getElementById(`vista-${vista}`).classList.remove("hidden");
  document.getElementById(`tab-btn-${vista}`).classList.add("active-tab");

  if (vista === "aule") renderVistaAule();
  if (vista === "giorno") renderPanoramicaGiorno();
}

function cercaAuleLibere() {
  if (!DATABASE) return;
  const giorno = document.getElementById("slot-giorno").value;
  const start = toMin(document.getElementById("slot-inizio").value);
  const end = toMin(document.getElementById("slot-fine").value);

  if (start >= end) {
    alert("L'orario di inizio deve precedere l'orario di fine.");
    return;
  }

  const griglia = document.getElementById("slot-risultati-griglia");
  griglia.innerHTML = "";
  let trovate = 0;

  for (const [nomeAula, schedule] of Object.entries(DATABASE.aule)) {
    const giornoData = schedule[giorno];
    if (!giornoData) continue;

    const fasciaIdonea = giornoData.fasce_libere.find(f => 
      toMin(f.orario_inizio) <= start && toMin(f.orario_fine) >= end
    );

    if (fasciaIdonea) {
      trovate++;
      const card = document.createElement("div");
      card.className = "room-card";
      card.innerHTML = `
        <div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 0.35rem;">
            <span class="room-card-title">${nomeAula}</span>
            <span class="badge-free">Libera</span>
          </div>
          <div class="free-slot-box">
            Fascia continua disponibile:<br>
            <strong>${fasciaIdonea.orario_inizio} - ${fasciaIdonea.orario_fine}</strong> (${fasciaIdonea.durata_minuti} min)
          </div>
        </div>
      `;
      griglia.appendChild(card);
    }
  }

  document.getElementById("slot-conteggio").innerText = `${trovate} aule disponibili`;
  if (trovate === 0) {
    griglia.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 3rem 1rem; text-align: center; color: var(--text-muted); font-weight: 600;">
        Nessuna aula completamente libera per la fascia ${document.getElementById("slot-inizio").value} - ${document.getElementById("slot-fine").value}.
      </div>
    `;
  }
}

function renderVistaAule() {
  if (!DATABASE) return;
  const contenitore = document.getElementById("aule-lista");
  const query = document.getElementById("filtro-nome-aula").value.trim().toLowerCase();
  const giornoFiltro = document.getElementById("filtro-giorno-aula").value;
  contenitore.innerHTML = "";

  const auleNomi = Object.keys(DATABASE.aule).filter(a => a.toLowerCase().includes(query)).sort();

  if (auleNomi.length === 0) {
    contenitore.innerHTML = `<div class="card-panel" style="text-align:center; color:var(--text-muted);">Nessuna aula trovata.</div>`;
    return;
  }

  auleNomi.forEach(nome => {
    const card = document.createElement("div");
    card.className = "room-detail-card";
    
    let blocchiGiorni = "";
    const schedule = DATABASE.aule[nome];

    for (const [giorno, data] of Object.entries(schedule)) {
      if (giornoFiltro !== "TUTTI" && giorno !== giornoFiltro) continue;

      const badgeLibera = data.lezioni.length === 0 
        ? `<span class="badge-free" style="margin-left: 0.5rem;">Libera intera giornata</span>` 
        : "";

      let lezioniHtml = data.lezioni.map(l => `
        <div class="busy-lecture-item">
          <strong>${l.orario_inizio} - ${l.orario_fine}</strong> • ${l.nome_insegnamento}
          <div style="font-size: 0.72rem; color: #b91c1c; margin-top: 2px;">
            ${l.corso_di_studio || ''} ${l.anno_corso ? '(' + l.anno_corso + ')' : ''} ${l.partizione ? '[' + l.partizione + ']' : ''}
          </div>
        </div>
      `).join("");

      let liberiHtml = data.fasce_libere.map(f => `
        <span class="free-slot-pill">
          ${f.orario_inizio} - ${f.orario_fine} (${f.durata_minuti}m)
        </span>
      `).join("");

      blocchiGiorni += `
        <div class="day-schedule-row">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 0.35rem;">
            <strong style="color: var(--text-main); font-size: 0.9rem;">${giorno}</strong>
            ${badgeLibera}
          </div>
          ${data.lezioni.length > 0 ? `<div style="margin-bottom: 0.45rem;">${lezioniHtml}</div>` : ''}
          <div style="display:flex; flex-wrap:wrap; align-items:center; gap: 0.25rem;">
            <span style="font-size: 0.72rem; font-weight: 700; color: var(--text-muted); margin-right: 0.25rem;">Fasce Libere:</span>
            ${liberiHtml}
          </div>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="room-detail-title">${nome}</div>
      <div>${blocchiGiorni}</div>
    `;
    contenitore.appendChild(card);
  });
}

function renderPanoramicaGiorno() {
  if (!DATABASE) return;
  const giorno = document.getElementById("panoramica-giorno").value;
  const durataMin = parseInt(document.getElementById("panoramica-durata-minima").value, 10);
  const container = document.getElementById("panoramica-tabella");

  let rows = "";
  const aule = Object.keys(DATABASE.aule).sort();

  aule.forEach(nome => {
    const data = DATABASE.aule[nome][giorno];
    if (!data) return;

    const fasceUtili = data.fasce_libere.filter(f => f.durata_minuti >= durataMin);
    if (fasceUtili.length === 0) return;

    const badges = fasceUtili.map(f => `
      <span class="free-slot-pill">
        ${f.orario_inizio} - ${f.orario_fine}
      </span>
    `).join("");

    rows += `
      <tr>
        <td style="font-weight: 800; font-size: 1rem; color: var(--text-main);">${nome}</td>
        <td>${badges}</td>
      </tr>
    `;
  });

  container.innerHTML = `
    <table class="panoramic-table">
      <thead>
        <tr>
          <th style="width: 25%;">Aula</th>
          <th>Fasce Libere (${giorno})</th>
        </tr>
      </thead>
      <tbody>
        ${rows || '<tr><td colspan="2" style="text-align:center; padding: 2rem; color: var(--text-muted);">Nessuna aula trovata con slot liberi superiori alla durata impostata.</td></tr>'}
      </tbody>
    </table>
  `;
}

document.addEventListener("DOMContentLoaded", initApp);