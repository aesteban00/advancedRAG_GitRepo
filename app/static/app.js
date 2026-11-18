/* ============================================================
   app.js - logica de la interfaz web (vanilla JS, sin frameworks).
   ============================================================ */

// Usuario: se ELIGE en el desplegable del panel izquierdo o se crea uno nuevo (se recuerda en localStorage).
//  - user_id: etiqueta que separa lo publico de lo privado; propietaria de sus documentos y de su memoria.
//    (No hay contrasenas: es una demo de un solo equipo.)
// El HILO (thread_id) no se escribe: lo define la SESION que se abre.
//  - thread_id: conversacion; la memoria corta (stm) es solo de ese hilo.
const userInput = document.getElementById("user-input");   // es un <select>: .value = usuario activo
const NEW_USER = "__new__";
const USER_RE = /^[A-Za-z0-9][A-Za-z0-9_.@-]{0,39}$/;
const knownUsers = new Map();   // user_id -> {files, repos, sessions}, viene de GET /users
let activeUser = localStorage.getItem("user_id") || "demo-user";
// Administrador: el usuario reservado "admin" puede eliminar lo PUBLICO de cualquiera. La contrasena se comprueba
// en el servidor; aqui solo se guarda en la sesion del navegador (sessionStorage) y se envia como cabecera.
const ADMIN = "admin";
let adminEnabled = false;
const adminToken = () => sessionStorage.getItem("admin_token") || "";
const isAdmin = () => activeUser === ADMIN && !!adminToken();
const adminHeaders = () => (isAdmin() ? { "X-Admin-Token": adminToken() } : {});
if (activeUser === ADMIN && !adminToken()) activeUser = "demo-user";   // sin sesion de admin no se arranca como admin
const savedUsers = () => { try { return JSON.parse(localStorage.getItem("known_users") || "[]"); } catch (e) { return []; } };
const rememberUser = (u) => localStorage.setItem("known_users", JSON.stringify([...new Set([...savedUsers(), u])]));

function renderUserSelect() {
  userInput.replaceChildren();
  // Usuarios con datos (servidor) + creados aqui aunque aun no tengan datos + el activo.
  for (const u of [...new Set([...knownUsers.keys(), ...savedUsers(), activeUser])].filter((x) => x !== ADMIN).sort()) {
    const s = knownUsers.get(u);
    userInput.add(new Option(s ? `${u} · ${s.files} docs · ${s.repos} repos` : `${u} · (nuevo)`, u));
  }
  if (adminEnabled) userInput.add(new Option("admin · administrador", ADMIN));
  userInput.add(new Option("+ Nuevo usuario…", NEW_USER));
  userInput.value = activeUser;
  document.getElementById("admin-note").hidden = !isAdmin();
}
async function loadUsers() {
  try { adminEnabled = !!(await (await fetch("/config")).json()).admin_enabled; } catch (e) { /* sin servidor */ }
  try {
    const list = await (await fetch("/users")).json();
    if (Array.isArray(list)) { knownUsers.clear(); list.forEach((u) => knownUsers.set(u.user_id, u)); }
  } catch (e) { /* sin servidor: se usan los recordados */ }
  renderUserSelect();
}
function showAdminLogin(show) {
  document.getElementById("admin-login").hidden = !show;
  document.getElementById("user-msg").textContent = "";
  if (show) { document.getElementById("user-new").hidden = true; const i = document.getElementById("admin-pass"); i.value = ""; i.focus(); }
}
async function adminLogin() {
  const token = document.getElementById("admin-pass").value;
  try {
    const res = await fetch("/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    sessionStorage.setItem("admin_token", token);
    showAdminLogin(false); switchUser(ADMIN);
  } catch (err) { document.getElementById("user-msg").textContent = err.message; }
}
function showNewUser(show) {
  if (show) document.getElementById("admin-login").hidden = true;
  document.getElementById("user-new").hidden = !show;
  document.getElementById("user-msg").textContent = "";
  if (show) { const i = document.getElementById("user-new-name"); i.value = ""; i.focus(); }
}
// Cambia de usuario: las sesiones y los documentos privados son por usuario.
function switchUser(u) { activeUser = u; renderUserSelect(); saveIds(); loadDocuments(); openThread(newThreadId()); }
function createUser() {
  const name = document.getElementById("user-new-name").value.trim();
  if (name.toLowerCase() === ADMIN) { document.getElementById("user-msg").textContent = "«admin» es un nombre reservado."; return; }
  if (!USER_RE.test(name)) {
    document.getElementById("user-msg").textContent = "Usa 1-40 caracteres: letras, números, _ . @ - (empezando por letra o número).";
    return;
  }
  rememberUser(name); showNewUser(false); switchUser(name);
}
userInput.addEventListener("change", () => {
  if (userInput.value === NEW_USER) { userInput.value = activeUser; showNewUser(true); return; }
  if (userInput.value === ADMIN && !isAdmin()) { userInput.value = activeUser; showAdminLogin(true); return; }   // pide la contrasena
  showNewUser(false); showAdminLogin(false); switchUser(userInput.value);
});
document.getElementById("admin-ok").addEventListener("click", adminLogin);
document.getElementById("admin-cancel").addEventListener("click", () => showAdminLogin(false));
document.getElementById("admin-pass").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); adminLogin(); }
  if (e.key === "Escape") showAdminLogin(false);
});
document.getElementById("user-new-ok").addEventListener("click", createUser);
document.getElementById("user-new-cancel").addEventListener("click", () => showNewUser(false));
document.getElementById("user-new-name").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); createUser(); }
  if (e.key === "Escape") showNewUser(false);
});
renderUserSelect();
loadUsers();

let threadId = localStorage.getItem("thread_id") || newThreadId();
const saveIds = () => {
  localStorage.setItem("user_id", userInput.value.trim());
  localStorage.setItem("thread_id", threadId);
};
function newThreadId() {
  return "hilo-" + Date.now().toString(36).slice(-6);
}
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

// Elementos marcados para borrar: claves "kind\u0001source".
const selected = new Set();
const docKey = (d) => `${d.kind || "file"}\u0001${d.source}`;
// Se puede eliminar lo propio; el administrador, ademas, lo PUBLICO de cualquiera. El servidor lo vuelve a comprobar.
const isMine = (d) => d.owner === currentUser() || (isAdmin() && d.visibility === "public");

function updateDeleteButton() {
  const n = selected.size;
  const btn = document.getElementById("doc-delete");
  btn.textContent = `Eliminar (${n})`;
  btn.disabled = n === 0;
  const mine = docs[activeTab].filter(isMine);
  const all = document.getElementById("doc-select-all");
  all.checked = mine.length > 0 && mine.every((d) => selected.has(docKey(d)));
  all.disabled = mine.length === 0;
}

function renderDocuments() {
  const list = document.getElementById("doc-list");
  list.innerHTML = "";
  const items = docs[activeTab];
  document.getElementById("doc-actions").hidden = !items.length;
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = activeTab === "public" ? "Aún no hay documentos públicos." : "No tienes documentos privados.";
    list.appendChild(li);
    return;
  }
  for (const d of items) {
    const li = document.createElement("li");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selected.has(docKey(d));
    cb.disabled = !isMine(d);
    if (cb.disabled) cb.title = isAdmin() ? "Es privado: solo su propietario puede eliminarlo"
                                          : `Solo su propietario (${d.owner}) puede eliminarlo: cambia el usuario`;
    cb.addEventListener("change", () => {
      cb.checked ? selected.add(docKey(d)) : selected.delete(docKey(d));
      updateDeleteButton();
    });
    const txt = document.createElement("span");
    txt.textContent = d.kind === "repo"
      ? `${d.source} · repo GitHub${d.language ? " · " + d.language : ""} · ${d.chunks} chunks de docs · por ${d.owner}`
      : `${d.source} · ${d.chunks} chunks · subido por ${d.owner}`;
    li.append(cb, txt);
    list.appendChild(li);
  }
  updateDeleteButton();
}

document.getElementById("doc-select-all").addEventListener("change", (e) => {
  for (const d of docs[activeTab].filter(isMine)) e.target.checked ? selected.add(docKey(d)) : selected.delete(docKey(d));
  renderDocuments();
});

// Elimina lo marcado: pide confirmacion (no se puede deshacer) y muestra el resumen.
async function deleteSelected() {
  const items = [...selected].map((k) => { const [kind, source] = k.split("\u0001"); return { kind, source }; });
  if (!items.length) return;
  const names = items.map((i) => (i.kind === "repo" ? "[repo] " : "") + i.source).join("\n");
  const others = isAdmin() ? [...docs.public, ...docs.private].filter((d) => selected.has(docKey(d)) && d.owner !== ADMIN).length : 0;
  const warn = others ? `\n\nATENCIÓN: ${others} elemento(s) pertenecen a OTROS usuarios (modo administrador).` : "";
  if (!confirm(`¿Eliminar ${items.length} elemento(s)?\n\n${names}${warn}\n\nSe borran sus fragmentos y lo que solo ellos aportaron al grafo. No se puede deshacer.`)) return;
  const status = document.getElementById("doc-status");
  const btn = document.getElementById("doc-delete");
  btn.disabled = true;
  status.className = "doc-status"; status.textContent = "Eliminando…";
  try {
    const { results } = await apiJson("/documents/delete", {
      method: "POST", headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ items, user_id: currentUser() }),
    });
    const ok = results.filter((r) => !r.error), bad = results.filter((r) => r.error);
    const sum = (k) => ok.reduce((n, r) => n + (r[k] || 0), 0);
    status.replaceChildren();
    const line = (cls, text) => { const p = document.createElement("div"); p.className = cls; p.textContent = text; status.appendChild(p); };
    if (ok.length) line("ok", `Eliminados ${ok.length} · ${sum("chunks_deleted")} fragmentos · ${sum("entities_deleted")} entidades · ${sum("edges_removed")} relaciones`);
    bad.forEach((r) => line("error", `${r.source}: ${r.error}`));
  } catch (err) {
    status.className = "doc-status error"; status.textContent = "Error: " + err.message;
  }
  selected.clear();
  loadDocuments(); loadStatus(); loadOverviewGraph(); loadUsers();
}
document.getElementById("doc-delete").addEventListener("click", deleteSelected);

async function loadDocuments() {
  try {
    const res = await fetch("/documents?user_id=" + encodeURIComponent(currentUser()));
    docs = await res.json();
    if (!res.ok) throw new Error(docs.detail || res.statusText);
  } catch (err) {
    console.error("loadDocuments:", err);
    docs = { public: [], private: [] };
  }
  const present = new Set([...docs.public, ...docs.private].map(docKey));
  for (const k of [...selected]) if (!present.has(k)) selected.delete(k);
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
// Etiqueta de ORIGEN de cada respuesta (debe quedar claro si viene de dentro o de fuera).
const ORIGINS = {
  internal: ["Conocimiento interno", "o-internal"],
  partial: ["Interno · parcial", "o-partial"],
  none: ["Sin información interna", "o-none"],
  external: ["Fuente externa", "o-external"],
  memory: ["Memoria de conversaciones", "o-memory"],
};
function addMessage(role, text, memory = null, documents = null, origin = "") {
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
  if (ORIGINS[origin]) {
    const o = document.createElement("span");
    o.className = "origin-badge " + ORIGINS[origin][1];
    o.textContent = ORIGINS[origin][0];
    div.prepend(o);
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

// Fragmentos recuperados y COMO se encontraron: por significado (vector), por palabras (BM25) o por ambos.
function showChunks(chunks) {
  const box = document.getElementById("chunks-box");
  box.replaceChildren();
  if (!chunks || !chunks.length) return;
  const det = document.createElement("details"); det.open = true;
  const sum = document.createElement("summary"); sum.textContent = `Fragmentos recuperados (${chunks.length})`; det.appendChild(sum);
  for (const c of chunks) {
    const row = document.createElement("div"); row.className = "chunk";
    const head = document.createElement("div"); head.className = "chunk-head";
    const name = document.createElement("span"); name.className = "chunk-src";
    name.textContent = `${c.source}${c.page ? " · pág. " + c.page : ""}`; head.appendChild(name);
    for (const m of c.found_by || []) {
      const b = document.createElement("span"); b.className = "tag " + m;
      b.textContent = (m === "bm25" ? "BM25" : "vector") + (c.ranks && c.ranks[m] ? " #" + c.ranks[m] : "");
      head.appendChild(b);
    }
    const sc = document.createElement("span"); sc.className = "chunk-score"; sc.textContent = c.score; head.appendChild(sc);
    row.appendChild(head);
    const txt = document.createElement("div"); txt.className = "chunk-text"; txt.textContent = (c.text || "").replace(/\s+/g, " "); row.appendChild(txt);
    det.appendChild(row);
  }
  box.appendChild(det);
}

function resetFlow() {
  document.getElementById("flow-steps").innerHTML = "";
  document.getElementById("flow-summary").innerHTML = "";
  document.getElementById("flow-empty").style.display = "none";
  document.getElementById("token-box").innerHTML = '<span class="status">Sin datos.</span>';
  document.getElementById("chunks-box").replaceChildren();
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
      addMessage("assistant", m.reply || "(respuesta no guardada)", m.memory, m.documents, m.origin);
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
    showChunks(flow.chunks);
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
    addMessage("assistant", ev.reply, ev.memory, ev.documents, ev.origin);
    showOrigin(ev.memory, ev.documents);
    showTokens(ev.tokens, Object.values(stepsSeen));
    showChunks(ev.chunks);
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
  document.getElementById("view-explain").hidden = name !== "explain";
  document.body.classList.toggle("explain-active", name === "explain");
  if (name === "explain") loadExplain();
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
    `Recuperación: ${cfg.retrieval.mode}<br />Búsqueda: ${cfg.retrieval.search_mode}<br />$rankFusion + $rerank + $graphLookup`;
}

function applyLlmVisibility() {
  const same = $("llm-same").checked;
  $("llm-graph").hidden = same;
  $("llm-chat-title").textContent = same ? "LLM (grafo + chat)" : "LLM de chat";
}

function fillConfigForm() {
  // Los limites de los deslizadores van ANTES que el valor: un range sin max recorta cualquier valor a 100.
  const [lo, hi] = cfg.options.chunk_size_range;
  $("chunk-size").min = lo; $("chunk-size").max = hi;
  $("chunk-overlap").min = 0; $("chunk-overlap").max = Math.floor(hi / 2);
  document.querySelector(`input[name=strategy][value=${cfg.ingest.strategy}]`).checked = true;
  document.querySelector(`input[name=mode][value=${cfg.retrieval.mode}]`).checked = true;
  document.querySelector(`input[name=search_mode][value=${cfg.retrieval.search_mode}]`).checked = true;
  updateSearchHelp();
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
const SEARCH_HELP = {
  hybrid: "La base de datos fusiona los dos rankings con Reciprocal Rank Fusion: lo mejor de ambos mundos.",
  vector: "Entiende sinónimos y paráfrasis, pero puede fallar con siglas, códigos o nombres propios.",
  bm25: "Acierta con términos exactos (p. ej. «RDL 19/2022»), pero no entiende sinónimos. No llama a Voyage.",
};
function updateSearchHelp() { $("search-help").textContent = SEARCH_HELP[radio("search_mode")] || ""; }
document.querySelectorAll("input[name=search_mode]").forEach((r) => r.addEventListener("change", updateSearchHelp));
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
    retrieval: { mode: radio("mode"), search_mode: radio("search_mode"), top_k: Number($("top-k").value), graph_depth: Number($("graph-depth").value) },
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
// Lanza una ingesta en segundo plano y muestra su progreso (GET /jobs/{id}).
// Si se corta la conexion, se reintenta: el trabajo sigue en el servidor.
async function runIngest(_btn, url, opts) {
  const log = $("ingest-log");
  const line = (cls, text) => { const li = document.createElement("li"); li.className = cls; li.textContent = text; log.appendChild(li); return li; };
  log.replaceChildren();
  line("step", "Enviando…");
  document.querySelectorAll("#view-config button").forEach((b) => (b.disabled = true));
  try {
    const { job_id } = await apiJson(url, opts);
    let job;
    for (;;) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        job = await apiJson("/jobs/" + job_id);
      } catch (err) {
        if (!(err instanceof TypeError)) throw err;          // error de red: reintentamos
        line("warn", "Sin conexión con el servidor, reintentando…");
        continue;
      }
      log.replaceChildren();
      const details = document.createElement("details"); details.open = true;
      details.appendChild(Object.assign(document.createElement("summary"), { textContent: `Progreso (${job.status === "running" ? "en curso" : job.status})` }));
      const pre = document.createElement("pre"); pre.className = "job-log"; pre.textContent = job.log.join("\n");
      details.appendChild(pre); log.appendChild(details);
      pre.scrollTop = pre.scrollHeight;
      if (job.status !== "running") break;
    }
    if (job.status === "error") throw new Error(job.error);
    const done = job.result || { results: [], errors: [] };
    if (job.status === "done") { line("ok", "Completado"); }
    logIngest(done);
  } catch (err) {
    line("error", "Error: " + (err.message || err));
  }
  document.querySelectorAll("#view-config button").forEach((b) => (b.disabled = false));
  loadDocuments(); loadStatus(); loadOverviewGraph(); loadUsers();
}
$("ingest-files").addEventListener("click", () => {
  const fd = new FormData();
  const files = [...$("files-input").files, ...$("folder-input").files];
  if (!files.length) return;
  // webkitRelativePath: el navegador sube todos los ficheros de la carpeta.
  files.forEach((f) => fd.append("files", f, f.webkitRelativePath || f.name));
  fd.append("user_id", currentUser()); fd.append("visibility", visibility);
  runIngest($("ingest-files"), "/ingest/files", { method: "POST", body: fd, headers: adminHeaders() });
});
$("ingest-github").addEventListener("click", () => {
  const urls = $("repo-urls").value.split("\n").map((u) => u.trim()).filter(Boolean);
  if (!urls.length) return;
  runIngest($("ingest-github"), "/ingest/github", { method: "POST", headers: { "Content-Type": "application/json", ...adminHeaders() },
    body: JSON.stringify({ urls, user_id: currentUser(), visibility }) });
});

// ---- Estado de Atlas ----
async function loadStatus() {
  const box = $("status-box");
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
  box.replaceChildren();
  try {
    const st = await apiJson("/status");
    // Indices de busqueda
    box.appendChild(el("h3", "", "Índices de búsqueda"));
    if (st.indexes.length) {
      const t = el("table", "status-table"); const head = t.createTHead().insertRow();
      ["Colección", "Índice", "Tipo", "Estado", "Consultable"].forEach((c) => head.appendChild(el("th", "", c)));
      const body = t.createTBody();
      for (const i of st.indexes) {
        const r = body.insertRow();
        r.appendChild(el("td", "", i.collection)); r.appendChild(el("td", "mono", i.name)); r.appendChild(el("td", "", i.type));
        const td = el("td"); td.appendChild(el("span", "pill " + (i.status === "READY" ? "ok" : "wait"), i.status || "?")); r.appendChild(td);
        r.appendChild(el("td", i.queryable ? "yes" : "no", i.queryable ? "✓" : "✗"));
      }
      box.appendChild(t);
    } else box.appendChild(el("p", "status", "Sin índices (¿falló la creación al arrancar? Revisa los logs [setup])."));
    // Recuentos
    box.appendChild(el("h3", "", "Contenido"));
    const tiles = el("div", "tiles");
    for (const [k, v] of Object.entries(st.counts)) { const t = el("div", "tile"); t.appendChild(el("b", "", String(v))); t.appendChild(el("span", "", k)); tiles.appendChild(t); }
    box.appendChild(tiles);
    if (st.error) box.appendChild(el("p", "warn", "Error: " + st.error));
  } catch (err) { box.appendChild(el("p", "warn", "Error: " + err.message)); }
}
$("refresh-status").addEventListener("click", loadStatus);

loadSettings();
showView(localStorage.getItem("view") || "chat");

// ---- Pop-up con el prompt del LLM de chat ----
async function showPrompt(e) {
  e.preventDefault();
  const body = document.getElementById("prompt-body");
  body.replaceChildren();
  try {
    const p = await apiJson("/prompt");
    const sec = (title, text) => {
      body.appendChild(Object.assign(document.createElement("h3"), { textContent: title }));
      body.appendChild(Object.assign(document.createElement("pre"), { className: "code", textContent: text }));
    };
    sec("1 · Respuesta con conocimiento interno (documentos y repos)", p.internal);
    sec("2 · Respuesta fuera de la base de conocimiento (solo si el usuario lo autoriza)", p.external);
    sec("3 · Respuesta solo con la memoria de conversaciones", p.memory);
    const note = document.createElement("p");
    note.className = "status";
    note.textContent = `Etiquetas de origen: ${p.tags.join(" · ")}. Si el contexto interno no basta, el modelo termina con «${p.offer}»; un «sí» en el turno siguiente activa el prompt 2.`;
    body.appendChild(note);
  } catch (err) { body.textContent = "Error: " + err.message; }
  document.getElementById("prompt-modal").hidden = false;
  document.getElementById("prompt-close").focus();
}
const closePrompt = () => { document.getElementById("prompt-modal").hidden = true; };
document.getElementById("prompt-link").addEventListener("click", showPrompt);
document.getElementById("prompt-close").addEventListener("click", closePrompt);
document.getElementById("prompt-modal").addEventListener("click", (e) => { if (e.target.id === "prompt-modal") closePrompt(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !document.getElementById("prompt-modal").hidden) closePrompt(); });
