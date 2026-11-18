/* explain.js - pestaña Explicación: pasos de ingesta y consulta, con la llamada real a MongoDB de cada uno. */
const exEl = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
let exCatalog = null;
let exSelected = null;

const EX_HINT = {
  aggregate: "Compass → Aggregations → elige la colección → pega el array de etapas.",
  find: "Compass → Find → elige la colección → pega el filtro en el campo Filter.",
  createSearchIndex: "Compass → Indexes → Search Indexes → Create → JSON → pega la definición.",
  insert: "Ejemplo de documento que escribe la aplicación (sirve para ver su forma en Compass).",
  update: "Ejemplo de escritura que hace la aplicación. Se ejecuta desde la app, no en Compass.",
  atlas: "Paso que ejecuta Atlas (no es una llamada de la app).",
  local: "Paso sin consulta a MongoDB.", llm: "Paso del modelo de lenguaje (no MongoDB).",
  agent: "Servicio de memoria de Agent Engine (no es una llamada directa).",
};

async function loadExplain() {
  const q = document.getElementById("explain-q").value.trim();
  try {
    exCatalog = await apiJson(`/explain?user_id=${encodeURIComponent(currentUser())}&question=${encodeURIComponent(q)}`);
  } catch (err) {
    document.getElementById("explain-status").textContent = "Error: " + err.message;
    return;
  }
  renderStatus(exCatalog.status);
  renderLanes();
  const s = [...exCatalog.ingest, ...exCatalog.query].find((x) => x.id === exSelected);
  if (s) showDetail(s);
}

// Estado real de la aplicacion (datos vivos).
function renderStatus(st) {
  const box = document.getElementById("explain-status");
  box.replaceChildren();
  const chip = (k, v) => { const c = exEl("span", "chip"); c.append(exEl("b", "", k + " "), document.createTextNode(String(v))); box.appendChild(c); };
  chip("BBDD", st.db); chip("Ingesta", st.strategy); chip("Embedding", st.embedding);
  chip("Trozo", `${st.chunk[0]}/${st.chunk[1]}`); chip("Recuperación", st.retrieval); chip("Búsqueda", st.search_mode);
  chip("Top K", st.top_k); chip("Profundidad", st.graph_depth); chip("LLM chat", st.chat_model); chip("Usuario", st.user);
  if (st.counts && !st.counts.error) {
    chip("chunks", st.counts.chunks_auto + st.counts.chunks_context + st.counts.chunks_multimodal);
    chip("entidades", st.counts.entidades);
  }
}

function renderLanes() {
  renderLane("boxes-ingest", exCatalog.ingest);
  renderLane("boxes-query", exCatalog.query);
}

function renderLane(id, steps) {
  const lane = document.getElementById(id);
  lane.replaceChildren();
  for (const s of steps) {
    const card = exEl("button", "box" + (s.id === exSelected ? " active" : ""));
    card.type = "button";
    card.append(exEl("span", `kind ${s.kind}`, s.kind), exEl("h3", "", s.title), exEl("p", "", s.summary));
    if (s.collection) card.appendChild(exEl("code", "coll", s.collection));
    card.addEventListener("click", () => { exSelected = s.id; renderLanes(); showDetail(s); });
    lane.appendChild(card);
  }
}

function showDetail(s) {
  const d = document.getElementById("explain-detail");
  d.replaceChildren();
  d.appendChild(exEl("span", `kind ${s.kind}`, s.kind));
  d.appendChild(exEl("h2", "", s.title));
  d.appendChild(exEl("p", "", s.summary));
  const meta = exEl("dl", "meta");
  const row = (k, v) => { if (v) meta.append(exEl("dt", "", k), exEl("dd", "", v)); };
  row("Base de datos", s.db);
  row("Colección", s.collection);
  row("Nota", s.note);
  d.appendChild(meta);
  if (s.code !== null && s.code !== undefined) {
    const text = JSON.stringify(s.code, null, 2);
    const bar = exEl("div", "code-bar");
    const copy = exEl("button", "btn", "Copiar");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(text); copy.textContent = "Copiado ✓"; }
      catch (e) { copy.textContent = "No se pudo copiar"; }
      setTimeout(() => (copy.textContent = "Copiar"), 1500);
    });
    bar.append(exEl("span", "hint", EX_HINT[s.kind] || ""), copy);
    d.appendChild(bar);
    d.appendChild(exEl("pre", "code", text));
    if (s.kind === "aggregate" && !s.runnable) d.appendChild(exEl("p", "warn", "Sustituye los marcadores <…> por valores reales antes de ejecutarlo."));
  }
}

document.getElementById("explain-refresh").addEventListener("click", loadExplain);
document.getElementById("explain-q").addEventListener("keydown", (e) => { if (e.key === "Enter") loadExplain(); });
