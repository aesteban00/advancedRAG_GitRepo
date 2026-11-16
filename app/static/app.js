/* ============================================================
   app.js - logica de la interfaz web (vanilla JS, sin frameworks).
   ============================================================ */

// Usuario: se edita en la caja del panel izquierdo (se guarda en localStorage).
//  - user_id: persona; propietaria de los PDFs privados y de su memoria.
// El HILO (thread_id) no se escribe: lo define la SESION que se abre.
//  - thread_id: conversacion; la memoria corta (stm) es solo de ese hilo.
const userInput = document.getElementById("user-input");
userInput.value = localStorage.getItem("user_id") || "demo-user";
let threadId = localStorage.getItem("thread_id") || newThreadId();
const saveIds = () => {
  localStorage.setItem("user_id", userInput.value.trim());
  localStorage.setItem("thread_id", threadId);
};
function newThreadId() {
  return "hilo-" + Date.now().toString(36).slice(-6);
}
// Al cambiar de usuario empezamos una sesion nueva (las sesiones son por usuario).
userInput.addEventListener("change", () => { loadDocuments(); openThread(newThreadId()); });
saveIds();

// Memoria: ON/OFF. Estado global del toggle. Empieza activada.
let useMemory = true;
// Indica si la memoria de Agent Engine esta configurada en el backend.
let memoryAvailable = true;

const currentUser = () => userInput.value.trim() || "demo-user";

// --- Visibilidad del PDF a indexar: publico / privado ---
let visibility = "public";
const visToggle = document.getElementById("visibility-toggle");
visToggle.addEventListener("click", () => {
  visibility = visibility === "public" ? "private" : "public";
  visToggle.dataset.visibility = visibility;
  visToggle.textContent = visibility === "public" ? "Público" : "Privado";
});

// --- Lista de documentos (pestañas Publicos / Mis privados) ---
let activeTab = "public";
let docs = { public: [], private: [] };

function renderDocuments() {
  const list = document.getElementById("doc-list");
  list.innerHTML = "";
  const items = docs[activeTab];
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = activeTab === "public" ? "Aún no hay documentos públicos." : "No tienes documentos privados.";
    list.appendChild(li);
    return;
  }
  for (const d of items) {
    const li = document.createElement("li");
    li.textContent = `${d.source} · ${d.chunks} chunks · subido por ${d.owner}`;
    list.appendChild(li);
  }
}

async function loadDocuments() {
  try {
    const res = await fetch("/documents?user_id=" + encodeURIComponent(currentUser()));
    docs = await res.json();
    if (!res.ok) throw new Error(docs.detail || res.statusText);
  } catch (err) {
    console.error("loadDocuments:", err);
    docs = { public: [], private: [] };
  }
  renderDocuments();
}

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    activeTab = t.dataset.tab;
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    renderDocuments();
  })
);

// Utilidad: agrega un mensaje al cuadro de chat.
function addMessage(role, text, memory = null, documents = null) {
  // Devuelve el div creado (para poder asociarle su flujo).
  const box = document.getElementById("chat-box");
  const div = document.createElement("div");
  div.className = "msg " + role;
  // Flags explicitos segun el tipo de memoria que aporto contexto:
  //  - stm: lo dicho antes en ESTA conversacion (memoria a corto plazo)
  //  - episodic/semantic: recuerdos consolidados de conversaciones pasadas
  if (memory) {
    const flags = [
      ["stm", "Memoria corta (esta conversación)"],
      ["episodic", "Memoria episódica (conversaciones pasadas)"],
      ["semantic", "Memoria semántica (hechos aprendidos)"],
    ];
    const wrap = document.createElement("div");
    for (const [key, label] of flags) {
      if (!memory[key]) continue;
      const tag = document.createElement("span");
      tag.className = "mem-flag " + key;
      tag.textContent = `${label}: ${memory[key]}`;
      wrap.appendChild(tag);
    }
    if (wrap.children.length) div.appendChild(wrap);
  }
  // Flag de origen: fragmentos recuperados de la BBDD (Atlas Vector Search).
  if (documents !== null) {
    let wrap = div.querySelector("div") || div.appendChild(document.createElement("div"));
    const tag = document.createElement("span");
    if (documents > 0) {
      tag.className = "mem-flag db";
      tag.textContent = `BBDD (Atlas): ${documents} fragmentos`;
    } else if (!wrap.children.length) {
      tag.className = "mem-flag llm";
      tag.textContent = "Solo LLM (sin memoria ni BBDD)";
    }
    if (tag.className) wrap.appendChild(tag);
  }
  const body = document.createElement("div");
  body.textContent = text;
  div.appendChild(body);
  box.appendChild(div);
  box.scrollTop = box.scrollHeight; // auto-scroll hacia abajo
  return div;
}

// --- Boton de Memoria (ON/OFF) ---
const memoryToggle = document.getElementById("memory-toggle");
memoryToggle.addEventListener("click", () => {
  if (!memoryAvailable) return; // si no hay memoria, no se puede alternar
  useMemory = !useMemory;
  memoryToggle.textContent = useMemory ? "Memoria: ON" : "Memoria: OFF";
  memoryToggle.setAttribute("aria-pressed", useMemory);
});

// Al cargar, preguntamos al backend si la memoria esta configurada.
// Si no lo esta, desactivamos el boton (queda en gris) y el chat va sin memoria.
async function initMemoryToggle() {
  try {
    const res = await fetch("/config");
    const data = await res.json();
    memoryAvailable = data.memory_available === true;
  } catch (err) {
    memoryAvailable = false;
  }

  if (!memoryAvailable) {
    useMemory = false;
    memoryToggle.disabled = true;
    memoryToggle.textContent = "Memoria: no disponible";
    memoryToggle.setAttribute("aria-pressed", "false");
  }
}
initMemoryToggle();

// --- Chat ---
document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("message-input");
  const question = input.value.trim();
  if (!question) return;

  userBubble = addMessage("user", question);
  input.value = "";

  resetFlow();
  stepsSeen = {};
  try {
    const res = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: question,
        thread_id: threadId,
        user_id: userInput.value.trim() || "demo-user",
        use_memory: useMemory, // envia el estado del toggle
      }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);

    // El servidor envia una linea JSON por evento: la leemos segun llega.
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // la ultima puede estar incompleta
      for (const line of lines) {
        if (line.trim()) handleEvent(JSON.parse(line));
      }
    }
  } catch (err) {
    addMessage("assistant", "Error: " + err.message);
  }
});

// --- Panel "Flujo de la peticion" ---
const ICONS = { running: "", done: "✓", error: "!", skipped: "–" };

// Tokens del turno mostrado: total + desglose por llamada al LLM.
function showTokens(tokens, steps) {
  const box = document.getElementById("token-box");
  if (!tokens || !tokens.total) {
    box.innerHTML = '<span class="status">Este turno no consumió tokens.</span>';
    return;
  }
  const row = (k, v, cls = "") => `<div class="row ${cls}"><span>${k}</span><span>${v}</span></div>`;
  let html = "";
  for (const st of steps || []) {
    if (st.tokens) html += row(st.label.replace(/^LLM · /, ""), `${st.tokens.prompt} → ${st.tokens.completion}`);
  }
  html += row("entrada", tokens.prompt) + row("salida", tokens.completion) + row("total", tokens.total, "total");
  box.innerHTML = html;
}

function resetFlow() {
  document.getElementById("flow-steps").innerHTML = "";
  document.getElementById("flow-summary").innerHTML = "";
  document.getElementById("flow-empty").style.display = "none";
  document.getElementById("token-box").innerHTML = '<span class="status">Sin datos.</span>';
}

// Crea o actualiza el paso con ese id (running -> done/error/skipped).
function updateStep(ev) {
  const list = document.getElementById("flow-steps");
  let li = document.getElementById("step-" + ev.id);
  if (!li) {
    li = document.createElement("li");
    li.id = "step-" + ev.id;
    list.appendChild(li);
  }
  li.className = ev.status;
  li.innerHTML = "";
  const dot = document.createElement("span");
  dot.className = "dot";
  dot.textContent = ICONS[ev.status] || "";
  const title = document.createElement("div");
  title.className = "title";
  title.textContent = ev.label;
  if (ev.ms !== undefined) {
    const ms = document.createElement("span");
    ms.className = "ms";
    ms.textContent = ev.ms + " ms";
    title.appendChild(ms);
  }
  li.append(dot, title);
  if (ev.detail) {
    const d = document.createElement("div");
    d.className = "detail";
    d.textContent = ev.detail;
    li.appendChild(d);
  }
}

// Resumen del ORIGEN de la respuesta (memoria / BBDD / solo LLM).
function showOrigin(memory, documents) {
  const fromMemory = memory.stm + memory.episodic + memory.semantic > 0;
  const parts = [];
  if (fromMemory) parts.push("Memoria");
  if (documents > 0) parts.push("BBDD");
  const el = document.createElement("div");
  el.className = "origin";
  el.textContent = "Origen del contexto: " + (parts.length ? parts.join(" + ") : "solo LLM");
  document.getElementById("flow-summary").appendChild(el);
}

// Burbuja de la pregunta en curso: al terminar le asociamos su flow_id.
let userBubble = null;

// Hace clicable una pregunta para ver su flujo en el panel derecho.
function attachFlow(bubble, flowId) {
  bubble.classList.add("has-flow");
  bubble.title = "Ver el flujo de esta petición";
  bubble.addEventListener("click", () => showFlow(flowId, bubble));
}

// --- Historial de sesiones (hilos), panel izquierdo ---
const currentThread = () => threadId;

async function loadSessions() {
  const list = document.getElementById("session-list");
  let sessions = [];
  try {
    const res = await fetch("/threads?user_id=" + encodeURIComponent(currentUser()));
    sessions = await res.json();
  } catch (err) {}
  list.innerHTML = "";
  if (!sessions.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Sin sesiones todavía.";
    list.appendChild(li);
    return;
  }
  for (const s of sessions) {
    const li = document.createElement("li");
    // Etiqueta: usuario_hilo_fecha (la primera pregunta va en el tooltip).
    const fecha = new Date(s.first).toLocaleDateString("sv-SE"); // AAAA-MM-DD
    li.textContent = `${currentUser()}_${s.thread_id}_${fecha}`;
    li.title = `${s.title} (${s.count} preguntas)`;
    li.classList.toggle("active", s.thread_id === currentThread());
    li.addEventListener("click", () => openThread(s.thread_id));
    list.appendChild(li);
  }
}

// Carga los mensajes de un hilo en el chat (y fija el hilo activo).
async function openThread(id) {
  threadId = id;
  saveIds();
  document.getElementById("chat-box").innerHTML = "";
  resetFlow();
  document.getElementById("flow-empty").style.display = "";
  try {
    const res = await fetch(`/threads/${encodeURIComponent(id)}?user_id=` + encodeURIComponent(currentUser()));
    const msgs = await res.json();
    for (const m of msgs) {
      attachFlow(addMessage("user", m.question), m.id);
      addMessage("assistant", m.reply || "(respuesta no guardada)", m.memory, m.documents);
    }
  } catch (err) {}
  loadSessions();
}

document.getElementById("new-session").addEventListener("click", () => {
  openThread(newThreadId());
});

// Pinchar una pregunta -> carga su flujo guardado y lo pinta a la derecha.
async function showFlow(flowId, bubble) {
  document.querySelectorAll(".msg.user.selected").forEach((b) => b.classList.remove("selected"));
  bubble.classList.add("selected");
  try {
    const res = await fetch(`/flows/${flowId}?user_id=` + encodeURIComponent(currentUser()));
    if (!res.ok) throw new Error("Flujo no encontrado");
    const flow = await res.json();
    resetFlow();
    flow.steps.forEach(updateStep);
    showOrigin(flow.memory, flow.documents);
    showTokens(flow.tokens, flow.steps);
    showChatGraph(flow.graph);
  } catch (err) {
    resetFlow();
    document.getElementById("flow-summary").textContent = "Error: " + err.message;
  }
}

let stepsSeen = {}; // ultimo estado de cada paso del turno en curso

function handleEvent(ev) {
  if (ev.type === "step") { updateStep(ev); stepsSeen[ev.id] = ev; }
  else if (ev.type === "result") {
    addMessage("assistant", ev.reply, ev.memory, ev.documents);
    showOrigin(ev.memory, ev.documents);
    showTokens(ev.tokens, Object.values(stepsSeen));
    showChatGraph(ev.graph);
    if (ev.flow_id && userBubble) {
      attachFlow(userBubble, ev.flow_id);
      userBubble.classList.add("selected");
    }
    loadSessions(); // refresca el historial (nueva sesion / orden)
  } else if (ev.type === "error") {
    addMessage("assistant", "Error: " + ev.message);
  }
}

// Carga inicial: documentos, historial y mensajes del hilo activo.
loadDocuments();
openThread(currentThread());



// ====================== Pestanas (Chat / Configuracion) ======================
function showView(name) {
  document.getElementById("view-chat").hidden = name !== "chat";
  document.getElementById("view-config").hidden = name !== "config";
  document.getElementById("view-graph").hidden = name !== "graph";
  document.querySelectorAll(".main-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  localStorage.setItem("view", name);
  if (name === "config") loadStatus();
  if (name === "graph" && !document.getElementById("gv-svg").childElementCount) loadOverviewGraph();
}
document.querySelectorAll(".main-tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

// ====================== Configuracion ======================
let cfg = null;
const $ = (id) => document.getElementById(id);
const radio = (name) => document.querySelector(`input[name=${name}]:checked`).value;
async function apiJson(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function fillEmbeddingSelect() {
  const s = radio("strategy");
  const sel = $("emb-model");
  sel.replaceChildren();
  for (const m of cfg.options.embedding_models[s]) sel.add(new Option(m, m));
  sel.value = cfg.embedding[s];
  $("emb-strategy-name").textContent = s;
  $("emb-help").textContent = s === "auto_embed"
    ? "autoEmbed: Atlas genera los vectores; cambiar de modelo crea un índice nuevo y Atlas re-embebe solo."
    : "Los vectores los genera la app con la API de Voyage AI.";
}

function updateChunkControls() {
  const auto = radio("strategy") === "auto_embed";
  const [lo, hi] = cfg.options.chunk_size_range;
  const size = $("chunk-size"), ov = $("chunk-overlap");
  size.min = lo; size.max = hi;
  size.disabled = ov.disabled = !auto;
  if (!auto) {
    const [fs, fo] = cfg.options.fixed_chunk;
    size.value = fs; ov.value = fo;
    $("chunk-help").textContent = "Tamaño y solape fijos para esta estrategia.";
  } else {
    $("chunk-help").textContent = "Elige tamaño y solape (solo con chunking manual + autoEmbed).";
  }
  ov.max = Math.floor(Number(size.value) / 2) - 1;
  if (Number(ov.value) > Number(ov.max)) ov.value = ov.max;
  $("chunk-size-val").textContent = size.value;
  $("chunk-overlap-val").textContent = ov.value;
}

function renderPipelineNote() {
  const s = cfg.ingest.strategy;
  const same = cfg.llm.same_for_all;
  $("pipeline-note").innerHTML =
    `Ingesta: ${s}<br />Embedding: ${cfg.embedding[s]}<br />` +
    `LLM chat: ${cfg.llm.chat.model}<br />LLM grafo: ${same ? "(el mismo)" : cfg.llm.graph.model}<br />` +
    `Recuperación: ${cfg.retrieval.mode}<br />$vectorSearch + $rerank + $graphLookup`;
}

function applyLlmVisibility() {
  const same = $("llm-same").checked;
  $("llm-graph").hidden = same;
  $("llm-chat-title").textContent = same ? "LLM (grafo + chat)" : "LLM de chat";
}

function fillConfigForm() {
  document.querySelector(`input[name=strategy][value=${cfg.ingest.strategy}]`).checked = true;
  document.querySelector(`input[name=mode][value=${cfg.retrieval.mode}]`).checked = true;
  $("chunk-size").value = cfg.ingest.chunk_size;
  $("chunk-overlap").value = cfg.ingest.chunk_overlap;
  $("build-graph").checked = cfg.ingest.build_graph;
  $("top-k").value = cfg.retrieval.top_k;
  $("graph-depth").value = cfg.retrieval.graph_depth;
  $("llm-same").checked = cfg.llm.same_for_all;
  for (const r of ["chat", "graph"]) {
    $(r + "-base-url").value = cfg.llm[r].base_url;
    $(r + "-model").value = cfg.llm[r].model;
    $(r + "-api-key").placeholder = cfg.llm[r].has_key ? "******** (configurada)" : "(sin clave)";
  }
  fillEmbeddingSelect(); updateChunkControls(); applyLlmVisibility(); renderPipelineNote();
}

async function loadSettings() {
  try { cfg = await apiJson("/settings"); fillConfigForm(); } catch (err) { $("settings-status").textContent = "Error: " + err.message; }
}

document.querySelectorAll("input[name=strategy]").forEach((r) => r.addEventListener("change", () => {
  if (radio("strategy") === "auto_embed") { $("chunk-size").value = cfg.ingest.chunk_size; $("chunk-overlap").value = cfg.ingest.chunk_overlap; }
  fillEmbeddingSelect(); updateChunkControls();
}));
$("chunk-size").addEventListener("input", updateChunkControls);
$("chunk-overlap").addEventListener("input", updateChunkControls);
$("llm-same").addEventListener("change", applyLlmVisibility);

$("save-settings").addEventListener("click", async () => {
  const s = radio("strategy");
  const body = {
    ingest: { strategy: s, build_graph: $("build-graph").checked },
    embedding: { [s]: $("emb-model").value },
    llm: { same_for_all: $("llm-same").checked,
           chat: { base_url: $("chat-base-url").value.trim(), model: $("chat-model").value.trim() },
           graph: { base_url: $("graph-base-url").value.trim(), model: $("graph-model").value.trim() } },
    retrieval: { mode: radio("mode"), top_k: Number($("top-k").value), graph_depth: Number($("graph-depth").value) },
    llm_keys: { chat: $("chat-api-key").value, graph: $("graph-api-key").value },
  };
  if (s === "auto_embed") { body.ingest.chunk_size = Number($("chunk-size").value); body.ingest.chunk_overlap = Number($("chunk-overlap").value); }
  try {
    cfg = await apiJson("/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("chat-api-key").value = $("graph-api-key").value = ""; // la clave no se queda en el DOM
    fillConfigForm(); loadStatus();
    $("settings-status").textContent = "Guardado ✓";
  } catch (err) { $("settings-status").textContent = "Error: " + err.message; }
});

// ---- Fuentes: ficheros, carpeta y repos ----
function logIngest(data) {
  const log = $("ingest-log");
  const add = (cls, txt) => { const li = document.createElement("li"); li.className = cls; li.textContent = txt; log.appendChild(li); };
  for (const r of data.results) {
    add("ok", r.repo
      ? `${r.repo} · ${r.entities} entidades · ${r.docs} docs · ${r.chunks} chunks`
      : `${r.source} · ${r.strategy}/${r.model} · ${r.chunks} chunks · ${r.entities} entidades`);
    (r.warnings || []).forEach((w) => add("warn", "⚠ " + w));
  }
  (data.skipped || []).forEach((f) => add("skip", "ignorado: " + f));
  (data.errors || []).forEach((e) => add("error", `${e.file}: ${e.error}`));
}
async function runIngest(btn, url, opts) {
  const log = $("ingest-log");
  log.replaceChildren();
  const li = document.createElement("li");
  li.textContent = "Procesando… (puede tardar: el LLM extrae el grafo)";
  log.appendChild(li);
  document.querySelectorAll("#view-config button").forEach((b) => (b.disabled = true));
  try { const data = await apiJson(url, opts); log.replaceChildren(); logIngest(data); }
  catch (err) { log.replaceChildren(); logIngest({ results: [], errors: [{ file: "", error: err.message }] }); }
  document.querySelectorAll("#view-config button").forEach((b) => (b.disabled = false));
  loadDocuments(); loadStatus(); loadOverviewGraph();
}
$("ingest-files").addEventListener("click", () => {
  const fd = new FormData();
  const files = [...$("files-input").files, ...$("folder-input").files];
  if (!files.length) return;
  // webkitRelativePath: el navegador sube todos los ficheros de la carpeta.
  files.forEach((f) => fd.append("files", f, f.webkitRelativePath || f.name));
  fd.append("user_id", currentUser()); fd.append("visibility", visibility);
  runIngest($("ingest-files"), "/ingest/files", { method: "POST", body: fd });
});
$("ingest-github").addEventListener("click", () => {
  const urls = $("repo-urls").value.split("\n").map((u) => u.trim()).filter(Boolean);
  if (!urls.length) return;
  runIngest($("ingest-github"), "/ingest/github", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls, user_id: currentUser(), visibility }) });
});

// ---- Estado de Atlas ----
async function loadStatus() {
  const t = $("status-table");
  t.replaceChildren();
  const row = (cells, head) => { const tr = t.insertRow(); cells.forEach((c) => { const td = document.createElement(head ? "th" : "td"); td.textContent = c; tr.appendChild(td); }); };
  try {
    const st = await apiJson("/status");
    row(["Colección", "Índice", "Tipo", "Estado", "Consultable"], true);
    st.indexes.forEach((i) => row([i.collection, i.name, i.type, i.status, i.queryable ? "✓" : "✗"]));
    row(["Recuentos", "", "", "", ""], true);
    Object.entries(st.counts).forEach(([k, v]) => row([k, v, "", "", ""]));
    if (st.error) row(["Error", st.error, "", "", ""]);
  } catch (err) { row(["Error", err.message, "", "", ""]); }
}
$("refresh-status").addEventListener("click", loadStatus);

loadSettings();
showView(localStorage.getItem("view") || "chat");
