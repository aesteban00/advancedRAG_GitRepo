/* graph.js - visor de grafo en SVG. Las posiciones las calcula NetworkX en el servidor. */
const TYPE_COLORS = { Repository:"#00684A", Library:"#016BF8", Database:"#B45AF2", Service:"#FFC010",
  Endpoint:"#DB3030", Team:"#00A35C", Organization:"#00A35C", File:"#889397", Class:"#5C6C75",
  Function:"#3D4F58", Document:"#B5C900", Concept:"#6FB7E9", Person:"#D58AF5" };
const SVGNS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}, text) => {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text; // textContent: nunca innerHTML con datos
  return e;
};

// ---- Zoom y desplazamiento (rueda = zoom, arrastrar = mover) ----
const views = {};  // por id de svg: {k, x, y, viewport}
function applyView(id) {
  const v = views[id];
  if (v && v.viewport) v.viewport.setAttribute("transform", `translate(${v.x} ${v.y}) scale(${v.k})`);
}
function zoomGraph(id, factor, cx = 500, cy = 350) {
  const v = views[id]; if (!v) return;
  const k = Math.min(8, Math.max(0.2, v.k * factor));
  v.x = cx - (cx - v.x) * (k / v.k); v.y = cy - (cy - v.y) * (k / v.k); v.k = k;
  applyView(id);
}
function resetView(id) { if (views[id]) { Object.assign(views[id], { k: 1, x: 0, y: 0 }); applyView(id); } }
function enableZoomPan(id) {
  const svg = document.getElementById(id);
  views[id] = { k: 1, x: 0, y: 0, viewport: null };
  const pt = (e) => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
  svg.addEventListener("wheel", (e) => { e.preventDefault(); const p = pt(e); zoomGraph(id, e.deltaY < 0 ? 1.15 : 1 / 1.15, p.x, p.y); }, { passive: false });
  let drag = null;
  svg.addEventListener("mousedown", (e) => { if (e.target.closest("g.node")) return; drag = pt(e); svg.style.cursor = "grabbing"; });
  window.addEventListener("mousemove", (e) => { if (!drag) return; const p = pt(e); views[id].x += p.x - drag.x; views[id].y += p.y - drag.y; drag = p; applyView(id); });
  window.addEventListener("mouseup", () => { drag = null; svg.style.cursor = "grab"; });
  svg.style.cursor = "grab";
}

let lastGraph = null;  // ultimo subgrafo del chat (para la pestana Grafo)

// Dibuja g = {nodes, edges}. ids: svg + info + leyenda (panel pequeno o pestana grande).
function renderGraph(g, svgId = "gv-svg", infoId = "gv-info", legendId = "gv-legend") {
  const svg = document.getElementById(svgId);
  const info = document.getElementById(infoId);
  const legend = document.getElementById(legendId);
  svg.replaceChildren(); legend.replaceChildren();
  const defs = svgEl("defs");
  const marker = svgEl("marker", { id: "arrow-" + svgId, viewBox: "0 0 10 10", refX: 18, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto" });
  marker.appendChild(svgEl("path", { d: "M0,0 L10,5 L0,10 z", fill: "#889397" }));
  defs.appendChild(marker); svg.appendChild(defs);
  const vp = svgEl("g");
  svg.appendChild(vp);
  if (!views[svgId]) enableZoomPan(svgId);
  views[svgId].viewport = vp; applyView(svgId);
  if (!g || !g.nodes || !g.nodes.length) { info.textContent = "Sin entidades del grafo."; return; }
  const big = true;
  const pos = {};
  g.nodes.forEach((n) => { pos[n.id] = [40 + n.x * 920, 40 + n.y * 620]; });
  for (const e of g.edges) {
    if (!pos[e.source] || !pos[e.target]) continue;
    const [x1, y1] = pos[e.source], [x2, y2] = pos[e.target];
    const line = svgEl("line", { x1, y1, x2, y2, stroke: "#b8c4c2", "stroke-width": 1.5, "marker-end": `url(#arrow-${svgId})` });
    line.appendChild(svgEl("title", {}, e.type));
    vp.appendChild(line);
    if (big || g.edges.length <= 40) vp.appendChild(svgEl("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2, "font-size": 11, fill: "#889397" }, e.type));
  }
  const types = new Set();
  for (const n of g.nodes) {
    types.add(n.type);
    const [x, y] = pos[n.id];
    const grp = svgEl("g", { class: "node", style: "cursor:pointer" });
    grp.appendChild(svgEl("circle", { cx: x, cy: y, r: n.highlight ? 14 : 9, fill: TYPE_COLORS[n.type] || "#999",
      stroke: n.highlight ? "#001E2B" : "#fff", "stroke-width": n.highlight ? 4 : 2 }));
    grp.appendChild(svgEl("text", { x: x + 13, y: y + 4, "font-size": big ? 13 : 16, fill: "#001E2B" },
      n.label.length > 28 ? n.label.slice(0, 28) + "…" : n.label));
    grp.appendChild(svgEl("title", {}, `${n.id} (${n.type})`));
    grp.addEventListener("click", () => loadEntityGraph(n.id, svgId));
    vp.appendChild(grp);
  }
  for (const t of types) {
    const item = document.createElement("span");
    item.className = "legend-item";
    const dot = document.createElement("i"); dot.style.background = TYPE_COLORS[t] || "#999";
    item.append(dot, t || "?"); legend.appendChild(item);
  }
  info.textContent = `${g.nodes.length} nodos · ${g.edges.length} relaciones · layout NetworkX · clic en un nodo para expandir`;
}

async function _loadGraph(url) {
  try {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    resetView("gv-svg"); renderGraph(data);
  } catch (err) { document.getElementById("gv-info").textContent = "Error: " + err.message; }
}
const loadOverviewGraph = () => _loadGraph("/graph?type=Repository");
const loadEntityGraph = (id) => _loadGraph("/graph?depth=2&entity=" + encodeURIComponent(id));

// Subgrafo de la respuesta del chat: se guarda para la pestana Grafo y se enlaza desde el flujo.
function showChatGraph(g) {
  lastGraph = g;
  const link = document.getElementById("flow-graph-link");
  if (g && g.nodes && g.nodes.length) {
    link.textContent = `Ver grafo de esta respuesta (${g.nodes.length} nodos) →`;
    link.hidden = false;
  } else { link.hidden = true; }
}
document.getElementById("flow-graph-link").addEventListener("click", () => {
  showView("graph"); resetView("gv-svg"); renderGraph(lastGraph);
});

document.getElementById("gv-overview").addEventListener("click", loadOverviewGraph);
document.getElementById("gv-last").addEventListener("click", () => { resetView("gv-svg"); renderGraph(lastGraph); });
document.getElementById("gv-entity").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.value.trim()) loadEntityGraph(e.target.value.trim());
});
document.getElementById("gv-in").addEventListener("click", () => zoomGraph("gv-svg", 1.3));
document.getElementById("gv-out").addEventListener("click", () => zoomGraph("gv-svg", 1 / 1.3));
document.getElementById("gv-reset").addEventListener("click", () => resetView("gv-svg"));
enableZoomPan("gv-svg");
