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

// Iconos (SVG en linea, sin imagenes externas). Color por proveedor: local=gris, Atlas=verde, LLM=morado.
const EX_ICON_PATHS = {
  "local/python": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',                         // </>
  "atlas/insert": '<path d="M12 5v14M5 12h14"/><rect x="3" y="3" width="18" height="18" rx="4"/>',  // + en caja
  "atlas/autoembedding": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>', // destello
  "atlas/index": '<path d="M4 6h16M4 12h10M4 18h7"/><circle cx="18" cy="16" r="3"/>',             // lista + busqueda
  "atlas/update": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/>',                      // lapiz
  "atlas/agent_memory": '<path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3V4z"/><path d="M15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3V4z"/>', // cerebro
  "atlas/aggregate": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17.5l9 5 9-5"/>', // capas
  "atlas/find": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',                     // lupa
  "LLM/update_grafo": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 7.5l8 .5M7.5 8l3.5 8M16.5 10.5l-3 5.5"/>', // nodos
  "LLM/chat": '<path d="M4 5h16v11H9l-5 4z"/>',                                                    // burbuja
};
const EX_ICON_COLOR = { "local/python": "#5b6b69", "atlas": "#00684A", "LLM": "#7c3aed" };
function exIconBadge(key) {
  const wrap = exEl("span", "icon-badge");
  const prov = key.split("/")[0];
  wrap.style.setProperty("--ic", EX_ICON_COLOR[key] || EX_ICON_COLOR[prov] || "#5b6b69");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "ic");
  svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  svg.innerHTML = EX_ICON_PATHS[key] || EX_ICON_PATHS["local/python"];
  wrap.append(svg, exEl("span", "icon-label", key));
  return wrap;
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
    card.append(exIconBadge(s.icon || "local/python"), exEl("h3", "", s.title), exEl("p", "", s.summary));
    if (s.collection) card.appendChild(exEl("code", "coll", s.collection));
    card.addEventListener("click", () => { exSelected = s.id; renderLanes(); showDetail(s); });
    lane.appendChild(card);
  }
}

// Pop-up con el codigo de un script: gris = codigo, verde = lineas que llaman a MongoDB.
async function openCode(path) {
  const box = document.getElementById("code-body");
  const title = document.getElementById("code-title");
  box.replaceChildren();
  title.textContent = path;
  document.getElementById("code-modal").hidden = false;
  document.getElementById("code-close").focus();
  try {
    const src = await apiJson("/explain/source?path=" + encodeURIComponent(path));
    title.textContent = `${src.path} · ${src.mongo_lines} líneas de MongoDB · ${src.memory_lines} de Agent Engine Memory`;
    let first = null;
    for (const l of src.lines) {
      const row = exEl("div", "cl" + (l.mongo ? " mg" : "") + (l.memory ? " am" : ""));
      row.append(exEl("span", "n", String(l.n)), exEl("span", "t", l.text || " "));
      box.appendChild(row);
      if ((l.mongo || l.memory) && !first) first = row;
    }
    if (first && first.scrollIntoView) first.scrollIntoView({ block: "center" });
  } catch (err) { box.textContent = "Error: " + err.message; }
}
const closeCode = () => { document.getElementById("code-modal").hidden = true; };
document.getElementById("code-close").addEventListener("click", closeCode);
document.getElementById("code-modal").addEventListener("click", (e) => { if (e.target.id === "code-modal") closeCode(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !document.getElementById("code-modal").hidden) closeCode(); });

function showDetail(s) {
  const d = document.getElementById("explain-detail");
  d.replaceChildren();
  d.hidden = false;
  d.appendChild(exIconBadge(s.icon || "local/python"));
  d.appendChild(exEl("h2", "", s.title));
  d.appendChild(exEl("p", "", s.summary));
  if (s.files && s.files.length) {
    const fw = exEl("div", "files");
    fw.appendChild(exEl("div", "files-title", "Script" + (s.files.length > 1 ? "s" : "") + " (pulsa para ver el código)"));
    for (const f of s.files) {
      const b = exEl("button", "file-chip", f);
      b.type = "button";
      b.addEventListener("click", () => openCode(f));
      fw.appendChild(b);
    }
    d.appendChild(fw);
  }
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

// Panel izquierdo en esta pestaña: aviso inicial hasta que se pulsa una caja.
(function initDetail() {
  const d = document.getElementById("explain-detail");
  d.replaceChildren(exEl("p", "status", "Pulsa un paso de la pestaña para ver aquí su llamada a MongoDB, lista para copiar en MongoDB Compass."));
})();
document.getElementById("explain-refresh").addEventListener("click", loadExplain);
document.getElementById("explain-q").addEventListener("keydown", (e) => { if (e.key === "Enter") loadExplain(); });

// ---- Separador del panel izquierdo: arrastrar = ancho; doble clic = contraer / expandir ----
(function sideResizer() {
  const KEY = "explain_side_w", DEFAULT = 300, MAX = 640;
  const handle = document.getElementById("side-resizer");
  const apply = (w) => {
    const v = Math.max(0, Math.min(MAX, Math.round(w)));
    document.documentElement.style.setProperty("--side-w", v + "px");
    document.body.classList.toggle("side-collapsed", v < 40);
    localStorage.setItem(KEY, String(v));
  };
  apply(Number(localStorage.getItem(KEY)) || DEFAULT);
  let start = null;
  handle.addEventListener("mousedown", (e) => {
    start = { x: e.clientX, w: parseFloat(getComputedStyle(document.querySelector(".sidebar")).width) || DEFAULT };
    document.body.classList.add("side-dragging");
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => { if (start) apply(start.w + (e.clientX - start.x)); });
  window.addEventListener("mouseup", () => { if (start) { start = null; document.body.classList.remove("side-dragging"); } });
  handle.addEventListener("dblclick", () => {
    const collapsed = document.body.classList.contains("side-collapsed");
    apply(collapsed ? DEFAULT : 0);
  });
})();
