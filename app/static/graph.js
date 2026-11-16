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

function renderGraph(g) {
  const svg = document.getElementById("graph-svg");
  const info = document.getElementById("graph-info");
  const legend = document.getElementById("graph-legend");
  svg.replaceChildren(); legend.replaceChildren();
  if (!g || !g.nodes || !g.nodes.length) { info.textContent = "Sin entidades del grafo para esta respuesta."; return; }
  const pos = {};
  g.nodes.forEach((n) => { pos[n.id] = [40 + n.x * 920, 40 + n.y * 620]; });
  const defs = svgEl("defs");
  const marker = svgEl("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 18, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto" });
  marker.appendChild(svgEl("path", { d: "M0,0 L10,5 L0,10 z", fill: "#889397" }));
  defs.appendChild(marker); svg.appendChild(defs);
  for (const e of g.edges) {
    if (!pos[e.source] || !pos[e.target]) continue;
    const [x1, y1] = pos[e.source], [x2, y2] = pos[e.target];
    const line = svgEl("line", { x1, y1, x2, y2, stroke: "#b8c4c2", "stroke-width": 1.5, "marker-end": "url(#arrow)" });
    line.appendChild(svgEl("title", {}, e.type));
    svg.appendChild(line);
    if (g.edges.length <= 40) svg.appendChild(svgEl("text", { x: (x1 + x2) / 2, y: (y1 + y2) / 2, "font-size": 14, fill: "#889397" }, e.type));
  }
  const types = new Set();
  for (const n of g.nodes) {
    types.add(n.type);
    const [x, y] = pos[n.id];
    const grp = svgEl("g", { style: "cursor:pointer" });
    grp.appendChild(svgEl("circle", { cx: x, cy: y, r: n.highlight ? 16 : 10, fill: TYPE_COLORS[n.type] || "#999",
      stroke: n.highlight ? "#001E2B" : "#fff", "stroke-width": n.highlight ? 4 : 2 }));
    grp.appendChild(svgEl("text", { x: x + 14, y: y + 5, "font-size": 16, fill: "#001E2B" },
      n.label.length > 24 ? n.label.slice(0, 24) + "…" : n.label));
    grp.appendChild(svgEl("title", {}, `${n.id} (${n.type})`));
    grp.addEventListener("click", () => loadEntityGraph(n.id));
    svg.appendChild(grp);
  }
  for (const t of types) {
    const item = document.createElement("span");
    item.className = "legend-item";
    const dot = document.createElement("i"); dot.style.background = TYPE_COLORS[t] || "#999";
    item.append(dot, t || "?"); legend.appendChild(item);
  }
  info.textContent = `${g.nodes.length} nodos · ${g.edges.length} relaciones · layout NetworkX · recorrido $graphLookup`;
}

async function _loadGraph(url) {
  try {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    renderGraph(data);
  } catch (err) { document.getElementById("graph-info").textContent = "Error: " + err.message; }
}
const loadOverviewGraph = () => _loadGraph("/graph?type=Repository");
const loadEntityGraph = (id) => _loadGraph("/graph?depth=2&entity=" + encodeURIComponent(id));

document.getElementById("graph-overview").addEventListener("click", loadOverviewGraph);
document.getElementById("graph-entity").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.value.trim()) loadEntityGraph(e.target.value.trim());
});
loadOverviewGraph();
