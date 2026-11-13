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
    li.textContent = `${d.filename} · ${d.chunks} chunks · subido por ${d.owner}`;
    list.appendChild(li);
  }
}

async function loadDocuments() {
  try {
    const res = await fetch("/documents?user_id=" + encodeURIComponent(currentUser()));
    docs = await res.json();
  } catch (err) {
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

// --- Subida de PDF ---
document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("pdf-input");
  const status = document.getElementById("upload-status");
  if (!input.files.length) return;

  const formData = new FormData();
  formData.append("file", input.files[0]);
  formData.append("user_id", currentUser());
  formData.append("visibility", visibility);

  status.textContent = "Procesando PDF...";
  try {
    const res = await fetch("/upload", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    status.textContent = data.message + ` (${data.chunks} chunks · modo: ${data.mode} · ${visibility === "public" ? "público" : "privado"})`;
    loadDocuments();
  } catch (err) {
    status.textContent = "Error: " + err.message;
  }
});

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
    if (!res.ok) throw new Error(res.statusText);

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


// --- Ajustes del LLM (solo en memoria del servidor; NO se guardan en el navegador) ---
async function loadLLMConfig() {
  try {
    const cfg = await (await fetch("/llm-config")).json();
    document.getElementById("llm-base-url").value = cfg.base_url;
    document.getElementById("llm-model").value = cfg.model;
    // Asteriscos = ya hay una LLM_API_KEY introducida (nunca se muestra su valor).
    document.getElementById("llm-api-key").placeholder = cfg.has_key ? "********" : "(sin clave)";
    // PIPELINE (panel izquierdo): LLM en uso.
    let host = cfg.base_url;
    try { host = new URL(cfg.base_url).host; } catch (e) {}
    document.getElementById("pipeline-llm").innerHTML =
      `LLM: ${cfg.model}<br />${host}<br />LLM_API_KEY: ${cfg.has_key ? "********" : "no definida"}`;
  } catch (err) {}
}
document.getElementById("llm-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const keyInput = document.getElementById("llm-api-key");
  const status = document.getElementById("llm-status");
  // La clave solo se envia si se ha escrito; vacia = se mantiene la actual.
  const body = {
    base_url: document.getElementById("llm-base-url").value,
    api_key: keyInput.value,
    model: document.getElementById("llm-model").value,
  };
  const res = await fetch("/llm-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  keyInput.value = ""; // no dejamos la clave en el DOM
  status.textContent = res.ok ? "Aplicado (solo en memoria)." : "Error al aplicar.";
  loadLLMConfig();
});
loadLLMConfig();
