/* graph.js - visor de grafo navegable (SVG). El layout inicial lo calcula NetworkX en el servidor;
   la expansion de nodos se hace en el cliente sin perder el contexto. */
const TYPE_COLORS = { Repository:"#00684A", Library:"#016BF8", Database:"#B45AF2", Service:"#FFC010",
  Endpoint:"#DB3030", Team:"#00A35C", Organization:"#00A35C", File:"#889397", Class:"#5C6C75",
  Function:"#3D4F58", Document:"#B5C900", Concept:"#6FB7E9", Person:"#D58AF5" };
const CODE_TYPES = ["File", "Class", "Function"];   // ruido de codigo: ocultos por defecto (casilla en la leyenda)
const SVGNS = "http://www.w3.org/2000/svg";
const $g = (id) => document.getElementById(id);
const svgEl = (tag, attrs = {}, text) => {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;   // textContent: nunca innerHTML con datos
  return e;
};
const color = (t) => TYPE_COLORS[t] || "#999";
const ekey = (e) => `${e.source}\u0001${e.target}\u0001${e.type}`;

// ---- Estado del grafo en pantalla ----
const S = { nodes: new Map(), edges: new Map(), owners: new Map(), expanded: new Set(),
            hiddenTypes: new Set(CODE_TYPES), hiddenRels: new Set(), selected: null,
            path: null, pathEdges: new Set() };
let lastGraph = null;   // ultimo subgrafo del chat

// ---- Zoom y desplazamiento (rueda = zoom, arrastrar el fondo = mover) ----
const view = { k: 1, x: 0, y: 0, vp: null };
function applyView() { if (view.vp) view.vp.setAttribute("transform", `translate(${view.x} ${view.y}) scale(${view.k})`); }
function zoomGraph(factor, cx = 500, cy = 350) {
  const k = Math.min(8, Math.max(0.2, view.k * factor));
  view.x = cx - (cx - view.x) * (k / view.k); view.y = cy - (cy - view.y) * (k / view.k); view.k = k;
  applyView();
}
function resetView() { Object.assign(view, { k: 1, x: 0, y: 0 }); applyView(); }
(function enableZoomPan() {
  const svg = $g("gv-svg");
  const pt = (e) => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
  svg.addEventListener("wheel", (e) => { e.preventDefault(); const p = pt(e); zoomGraph(e.deltaY < 0 ? 1.15 : 1 / 1.15, p.x, p.y); }, { passive: false });
  let drag = null;
  svg.addEventListener("mousedown", (e) => { if (e.target.closest("g.node")) return; drag = pt(e); svg.style.cursor = "grabbing"; });
  window.addEventListener("mousemove", (e) => { if (!drag) return; const p = pt(e); view.x += p.x - drag.x; view.y += p.y - drag.y; drag = p; applyView(); });
  window.addEventListener("mouseup", () => { drag = null; svg.style.cursor = "grab"; });
  svg.style.cursor = "grab";
})();

// ---- Carga y fusion de grafos ----
function ownerAdd(id, key) { if (!S.owners.has(id)) S.owners.set(id, new Set()); S.owners.get(id).add(key); }

// Sustituye el grafo entero (resumen, chat, camino, busqueda).
function setGraph(g, path = null) {
  Object.assign(S, { nodes: new Map(), edges: new Map(), owners: new Map(), expanded: new Set(), selected: null,
                     path: path ? new Set(path) : null, pathEdges: new Set() });
  for (const n of (g && g.nodes) || []) { S.nodes.set(n.id, { ...n, px: 40 + n.x * 920, py: 40 + n.y * 620 }); ownerAdd(n.id, "base"); }
  for (const e of (g && g.edges) || []) S.edges.set(ekey(e), e);
  if (path) for (let i = 0; i < path.length - 1; i++) {
    for (const e of S.edges.values()) if ((e.source === path[i] && e.target === path[i + 1]) || (e.source === path[i + 1] && e.target === path[i])) S.pathEdges.add(ekey(e));
  }
  resetView(); closeDetail(); render();
}

// Anade el vecindario directo de un nodo al grafo actual (sin recolocar lo que ya estaba).
async function expandNode(id) {
  if (S.expanded.has(id)) return;
  const data = await fetchJson("/graph?depth=0&entity=" + encodeURIComponent(id));
  const parent = S.nodes.get(id);
  const fresh = data.nodes.filter((n) => !S.nodes.has(n.id));
  const r = Math.min(170, 70 + fresh.length * 6);
  fresh.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, fresh.length);
    S.nodes.set(n.id, { ...n, px: (parent ? parent.px : 500) + r * Math.cos(a), py: (parent ? parent.py : 350) + r * Math.sin(a) });
  });
  data.nodes.forEach((n) => ownerAdd(n.id, id));
  for (const e of data.edges) { const k = ekey(e); if (!S.edges.has(k)) S.edges.set(k, e); }
  S.expanded.add(id);
  render();
}
// Quita lo que solo habia aportado la expansion de ese nodo.
function collapseNode(id) {
  S.expanded.delete(id);
  for (const [nid, owners] of [...S.owners]) {
    owners.delete(id);
    if (!owners.size) { S.owners.delete(nid); S.nodes.delete(nid); }
  }
  for (const [k, e] of [...S.edges]) if (!S.nodes.has(e.source) || !S.nodes.has(e.target)) S.edges.delete(k);
  render();
}

async function fetchJson(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}
const info = (t) => { $g("gv-info").textContent = t; };
async function loadOverviewGraph() {
  try { setGraph(await fetchJson("/graph")); } catch (err) { info("Error: " + err.message); }
}
async function loadEntityGraph(id) {
  try { setGraph(await fetchJson("/graph?depth=0&entity=" + encodeURIComponent(id))); await selectNode(id); }
  catch (err) { info("Error: " + err.message); }
}

// ---- Dibujo (aplica los filtros sin volver al servidor) ----
function render() {
  const svg = $g("gv-svg");
  svg.replaceChildren();
  const defs = svgEl("defs");
  const mk = svgEl("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 18, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto" });
  mk.appendChild(svgEl("path", { d: "M0,0 L10,5 L0,10 z", fill: "#889397" }));
  defs.appendChild(mk); svg.appendChild(defs);
  const vp = svgEl("g"); svg.appendChild(vp); view.vp = vp; applyView();

  // Con un camino se muestra completo; si no, se aplican los filtros de tipo y relacion.
  const nodeOk = (n) => S.path ? S.path.has(n.id) : !S.hiddenTypes.has(n.type);
  const nodes = [...S.nodes.values()].filter(nodeOk);
  const ids = new Set(nodes.map((n) => n.id));
  const edges = [...S.edges.values()].filter((e) => ids.has(e.source) && ids.has(e.target) && (S.path || !S.hiddenRels.has(e.type)));
  const deg = {};
  edges.forEach((e) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });

  for (const e of edges) {
    const a = S.nodes.get(e.source), b = S.nodes.get(e.target);
    const onPath = S.pathEdges.has(ekey(e));
    const line = svgEl("line", { x1: a.px, y1: a.py, x2: b.px, y2: b.py, stroke: onPath ? "#F26B00" : "#b8c4c2",
      "stroke-width": onPath ? 4 : 1.5, "marker-end": "url(#arrow)" });
    line.appendChild(svgEl("title", {}, e.type));
    vp.appendChild(line);
    if (onPath || edges.length <= 40) vp.appendChild(svgEl("text", { x: (a.px + b.px) / 2, y: (a.py + b.py) / 2, "font-size": 11, fill: onPath ? "#F26B00" : "#889397" }, e.type));
  }
  for (const n of nodes) {
    const grp = svgEl("g", { class: "node", style: "cursor:pointer" });
    const sel = S.selected === n.id, onPath = S.path && S.path.has(n.id);
    const r = 8 + Math.min(10, (deg[n.id] || 0) * 0.8) + (n.highlight ? 3 : 0);   // tamano = conexiones
    grp.appendChild(svgEl("circle", { cx: n.px, cy: n.py, r, fill: color(n.type),
      stroke: sel ? "#F26B00" : onPath ? "#F26B00" : n.highlight ? "#001E2B" : "#fff", "stroke-width": sel || onPath ? 4 : n.highlight ? 3 : 2 }));
    if (S.expanded.has(n.id)) grp.appendChild(svgEl("circle", { cx: n.px, cy: n.py, r: r + 5, fill: "none", stroke: color(n.type), "stroke-dasharray": "3 3" }));
    grp.appendChild(svgEl("text", { x: n.px + r + 4, y: n.py + 4, "font-size": 13, fill: "#001E2B" }, n.label.length > 28 ? n.label.slice(0, 28) + "…" : n.label));
    grp.appendChild(svgEl("title", {}, `${n.id} (${n.type})`));
    grp.addEventListener("click", () => selectNode(n.id));
    grp.addEventListener("dblclick", () => toggleExpand(n.id));
    vp.appendChild(grp);
  }
  renderLegends();
  const hidden = S.nodes.size - nodes.length;
  info(`${nodes.length} nodos · ${edges.length} relaciones` + (hidden && !S.path ? ` · ${hidden} ocultos por filtro` : "") +
       " · clic = detalle · doble clic = expandir/colapsar");
}

function renderLegends() {
  const tl = $g("gv-legend"), rl = $g("gv-rel-legend");
  tl.replaceChildren(); rl.replaceChildren();
  const mk = (box, label, checked, onChange, dotColor) => {
    const l = document.createElement("label"); l.className = "legend-item";
    const c = document.createElement("input"); c.type = "checkbox"; c.checked = checked; c.disabled = !!S.path;
    c.addEventListener("change", () => { onChange(c.checked); render(); });
    l.appendChild(c);
    if (dotColor) { const d = document.createElement("i"); d.style.background = dotColor; l.appendChild(d); }
    l.append(label); box.appendChild(l);
  };
  const types = [...new Set([...S.nodes.values()].map((n) => n.type))].sort();
  const rels = [...new Set([...S.edges.values()].map((e) => e.type))].sort();
  // Todos / Ninguno: marca o desmarca de golpe todos los filtros de la fila.
  const bulk = (box, values, hidden) => {
    for (const [label, show] of [["Todos", true], ["Ninguno", false]]) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "btn bulk"; b.textContent = label; b.disabled = !!S.path;
      b.addEventListener("click", () => {
        for (const v of values) { show ? hidden.delete(v) : hidden.add(v); }
        render();
      });
      box.appendChild(b);
    }
  };
  bulk(tl, types, S.hiddenTypes);
  for (const t of types) mk(tl, t || "?", !S.hiddenTypes.has(t), (on) => on ? S.hiddenTypes.delete(t) : S.hiddenTypes.add(t), color(t));
  bulk(rl, rels, S.hiddenRels);
  for (const t of rels) mk(rl, t || "?", !S.hiddenRels.has(t), (on) => on ? S.hiddenRels.delete(t) : S.hiddenRels.add(t));
}

// ---- Panel de detalle ----
function closeDetail() { $g("gv-detail").hidden = true; $g("gv-hint").hidden = false; }
async function toggleExpand(id) { try { S.expanded.has(id) ? collapseNode(id) : await expandNode(id); if (S.selected === id) graphShowDetail(id); } catch (err) { info("Error: " + err.message); } }
async function selectNode(id) {
  S.selected = id; render();
  await graphShowDetail(id);
}
// Navega a un nodo relacionado: lo trae al grafo si falta, muestra su tipo si estaba filtrado,
// expande su vecindario (para poder seguir navegando) y centra la vista en el.
async function goTo(id) {
  if (S.path) { S.path = null; S.pathEdges = new Set(); }          // salir del modo "camino"
  if (!S.nodes.has(id) && S.selected) await expandNode(S.selected);
  if (!S.nodes.has(id)) await expandNode(id).catch(() => {});
  const n = S.nodes.get(id);
  if (n) S.hiddenTypes.delete(n.type);                              // que no quede oculto por un filtro
  if (!S.expanded.has(id)) await expandNode(id).catch(() => {});
  S.selected = id; render();
  const m = S.nodes.get(id);
  if (m) { view.x = 500 - m.px * view.k; view.y = 350 - m.py * view.k; applyView(); }   // centrar
  await graphShowDetail(id);
}
async function graphShowDetail(id) {
  const box = $g("gv-detail");
  box.hidden = false; box.replaceChildren(); $g("gv-hint").hidden = true;
  let d;
  try { d = await fetchJson("/graph/entity?id=" + encodeURIComponent(id)); }
  catch (err) { box.textContent = "Error: " + err.message; return; }
  const add = (tag, text, cls) => { const e = document.createElement(tag); if (cls) e.className = cls; e.textContent = text; box.appendChild(e); return e; };
  const head = add("h3", d.id); const badge = document.createElement("span");
  badge.className = "badge"; badge.textContent = d.type; badge.style.background = color(d.type); head.appendChild(badge);
  const bar = document.createElement("div"); bar.className = "detail-actions";
  const btn = (label, fn) => { const b = document.createElement("button"); b.type = "button"; b.className = "btn"; b.textContent = label; b.addEventListener("click", fn); bar.appendChild(b); };
  btn(S.expanded.has(id) ? "Colapsar" : "Expandir", () => toggleExpand(id));
  btn("Camino desde aquí", () => { $g("gv-from").value = id; });
  btn("Camino hasta aquí", () => { $g("gv-to").value = id; });
  btn("Cerrar", closeDetail);
  box.appendChild(bar);
  const attrs = Object.entries(d.attributes).filter(([, v]) => v && v.length);
  if (attrs.length) { add("h4", "Atributos"); const dl = document.createElement("dl");
    for (const [k, v] of attrs) { const dt = document.createElement("dt"); dt.textContent = k; const dd = document.createElement("dd"); dd.textContent = [].concat(v).join(", ").slice(0, 400); dl.append(dt, dd); }
    box.appendChild(dl); }
  if (d.sources.length) { add("h4", "Fuentes"); const ul = document.createElement("ul"); d.sources.forEach((s) => { const li = document.createElement("li"); li.textContent = s; ul.appendChild(li); }); box.appendChild(ul); }
  const rels = (title, list, arrow) => {
    add("h4", `${title} (${list.length})`);
    const ul = document.createElement("ul"); ul.className = "rels";
    for (const r of list.slice(0, 60)) {
      const li = document.createElement("li"); const a = document.createElement("a"); a.href = "#";
      a.textContent = arrow === "out" ? `${r.rel} → ${r.id}` : `${r.id} → ${r.rel}`;
      a.addEventListener("click", (e) => { e.preventDefault(); goTo(r.id); });
      li.appendChild(a); ul.appendChild(li);
    }
    box.appendChild(ul);
  };
  rels("Relaciones salientes", d.outgoing, "out");
  rels("Relaciones entrantes", d.incoming, "in");
}

// ---- Camino entre dos entidades ----
async function showPath() {
  const a = $g("gv-from").value.trim(), b = $g("gv-to").value.trim();
  if (!a || !b) { info("Indica origen y destino del camino."); return; }
  try {
    const r = await fetchJson(`/graph/path?source=${encodeURIComponent(a)}&target=${encodeURIComponent(b)}`);
    if (!r.found) { info(`No hay camino entre "${a}" y "${b}" (hasta 6 saltos).`); return; }
    setGraph(r.graph, r.path);
    info(`Camino (${r.path.length - 1} saltos${r.direction === "reverse" ? ", sentido inverso" : ""}): ` + r.path.join(" → "));
  } catch (err) { info("Error: " + err.message); }
}

// ---- Chat: subgrafo de la ultima respuesta ----
function showChatGraph(g) {
  lastGraph = g;
  const link = $g("flow-graph-link");
  if (g && g.nodes && g.nodes.length) { link.textContent = `Ver grafo de esta respuesta (${g.nodes.length} nodos) →`; link.hidden = false; }
  else link.hidden = true;
}
$g("flow-graph-link").addEventListener("click", () => { showView("graph"); setGraph(lastGraph); });

// ---- Autocompletado (datalist alimentado por /graph/search) ----
function attachSearch(input) {
  let t;
  input.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      if (input.value.trim().length < 2) return;
      try {
        const res = await fetchJson("/graph/search?q=" + encodeURIComponent(input.value.trim()));
        const dl = $g("gv-datalist"); dl.replaceChildren();
        for (const r of res) { const o = document.createElement("option"); o.value = r.id; o.label = r.type; dl.appendChild(o); }
      } catch (e) { /* el autocompletado es opcional */ }
    }, 250);
  });
}
["gv-entity", "gv-from", "gv-to"].forEach((id) => attachSearch($g(id)));

// ---- Controles ----
$g("gv-overview").addEventListener("click", loadOverviewGraph);
// Reset: limpia la busqueda, los campos de camino y la ficha, y vuelve al resumen.
$g("gv-reset-search").addEventListener("click", () => {
  for (const id of ["gv-entity", "gv-from", "gv-to"]) $g(id).value = "";
  S.selected = null;
  closeDetail();
  loadOverviewGraph();
});
$g("gv-last").addEventListener("click", () => setGraph(lastGraph));
$g("gv-entity").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.value.trim()) loadEntityGraph(e.target.value.trim()); });
$g("gv-path").addEventListener("click", showPath);
$g("gv-in").addEventListener("click", () => zoomGraph(1.3));
$g("gv-out").addEventListener("click", () => zoomGraph(1 / 1.3));
$g("gv-reset").addEventListener("click", resetView);
