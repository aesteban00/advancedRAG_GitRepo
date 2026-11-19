/* autoembed.js - pestaña "¿Por qué Autoembedding?": dibuja los dos esquemas de Excalidraw como SVG.
   Cada panel tiene su propia barra de scroll horizontal. Sin dependencias. */
const AE_SVG = "http://www.w3.org/2000/svg";
const AE_PAD = 24;
const AE_FILES = { "ae-con": "arch_CON_autoembedding.excalidraw", "ae-sin": "arch_SIN_autoembedding.excalidraw" };

// Caja que ocupa un elemento (las flechas usan sus puntos relativos).
function aeBox(e) {
  if ((e.type === "arrow" || e.type === "line") && e.points && e.points.length) {
    const xs = e.points.map((p) => e.x + p[0]), ys = e.points.map((p) => e.y + p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }
  return [e.x, e.y, e.x + (e.width || 0), e.y + (e.height || 0)];
}

function renderExcalidraw(data, host) {
  const els = (data.elements || []).filter((e) => !e.isDeleted);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const e of els) { const [a, b, c, d] = aeBox(e); x0 = Math.min(x0, a); y0 = Math.min(y0, b); x1 = Math.max(x1, c); y1 = Math.max(y1, d); }
  if (!isFinite(x0)) { host.textContent = "Sin contenido."; return; }
  const W = Math.ceil(x1 - x0 + 2 * AE_PAD), H = Math.ceil(y1 - y0 + 2 * AE_PAD);
  const scale = aeZoom();
  const sx = (x) => x - x0 + AE_PAD, sy = (y) => y - y0 + AE_PAD;
  const el = (tag, attrs = {}) => { const n = document.createElementNS(AE_SVG, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  // El viewBox es el tamaño natural; width/height lo escalan (el zoom no cambia la geometría).
  const svg = el("svg", { width: Math.round(W * scale), height: Math.round(H * scale), viewBox: `0 0 ${W} ${H}`, class: "ae-svg" });
  svg.dataset.w = W; svg.dataset.h = H;

  // Un marcador de flecha por color usado.
  const defs = el("defs"); const markers = {};
  const marker = (color) => {
    if (!markers[color]) {
      const id = "ae-m-" + color.replace(/[^a-z0-9]/gi, "") + "-" + Object.keys(markers).length;
      const m = el("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
      m.appendChild(el("path", { d: "M0,0 L10,5 L0,10 z", fill: color }));
      defs.appendChild(m); markers[color] = id;
    }
    return `url(#${markers[color]})`;
  };
  const dash = (e) => (e.strokeStyle === "dashed" ? "10 7" : e.strokeStyle === "dotted" ? "2 6" : null);
  const common = (e) => {
    const o = { stroke: e.strokeColor || "#1e1e1e", "stroke-width": e.strokeWidth || 2, "stroke-linecap": "round", "stroke-linejoin": "round" };
    const d = dash(e); if (d) o["stroke-dasharray"] = d;
    if (e.opacity != null && e.opacity < 100) o.opacity = e.opacity / 100;
    return o;
  };
  const fill = (e) => (!e.backgroundColor || e.backgroundColor === "transparent" ? "none" : e.backgroundColor);

  const body = el("g");
  for (const e of els) {
    if (e.type === "rectangle") {
      body.appendChild(el("rect", { x: sx(e.x), y: sy(e.y), width: e.width, height: e.height, rx: e.roundness ? 14 : 0, fill: fill(e), ...common(e) }));
    } else if (e.type === "ellipse") {
      body.appendChild(el("ellipse", { cx: sx(e.x) + e.width / 2, cy: sy(e.y) + e.height / 2, rx: e.width / 2, ry: e.height / 2, fill: fill(e), ...common(e) }));
    } else if (e.type === "diamond") {
      const cx = sx(e.x) + e.width / 2, cy = sy(e.y) + e.height / 2;
      body.appendChild(el("polygon", { points: `${cx},${sy(e.y)} ${sx(e.x) + e.width},${cy} ${cx},${sy(e.y) + e.height} ${sx(e.x)},${cy}`, fill: fill(e), ...common(e) }));
    } else if ((e.type === "arrow" || e.type === "line") && e.points) {
      const pts = e.points.map((p) => `${sx(e.x + p[0])},${sy(e.y + p[1])}`).join(" ");
      const o = { points: pts, fill: "none", ...common(e) };
      if (e.endArrowhead) o["marker-end"] = marker(e.strokeColor || "#1e1e1e");
      if (e.startArrowhead) o["marker-start"] = marker(e.strokeColor || "#1e1e1e");
      body.appendChild(el("polyline", o));
    } else if (e.type === "text" && e.text) {
      const size = e.fontSize || 16, lh = size * 1.25;
      const align = e.textAlign || "left";
      const anchor = align === "center" ? "middle" : align === "right" ? "end" : "start";
      const x = align === "center" ? sx(e.x) + (e.width || 0) / 2 : align === "right" ? sx(e.x) + (e.width || 0) : sx(e.x);
      const t = el("text", { x, y: sy(e.y), "text-anchor": anchor, "dominant-baseline": "hanging", "font-size": size,
                             "font-family": "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", fill: e.strokeColor || "#1e1e1e" });
      e.text.split("\n").forEach((line, i) => {
        const ts = el("tspan", { x, dy: i === 0 ? 0 : lh });
        ts.textContent = line; t.appendChild(ts);
      });
      body.appendChild(t);
    }
  }
  svg.appendChild(defs); svg.appendChild(body);
  host.replaceChildren(svg);
}

// ---- Zoom compartido por los dos esquemas (se recuerda en el navegador; por defecto 50 %) ----
const AE_ZOOM = { key: "ae_zoom", def: 0.5, min: 0.2, max: 2 };
function aeZoom() {
  const v = parseFloat(localStorage.getItem(AE_ZOOM.key));
  return isFinite(v) ? Math.min(AE_ZOOM.max, Math.max(AE_ZOOM.min, v)) : AE_ZOOM.def;
}
function aeSetZoom(z) {
  const v = Math.min(AE_ZOOM.max, Math.max(AE_ZOOM.min, Math.round(z * 100) / 100));
  localStorage.setItem(AE_ZOOM.key, String(v));
  document.querySelectorAll("#view-autoembed svg.ae-svg").forEach((s) => {
    s.setAttribute("width", Math.round(s.dataset.w * v));
    s.setAttribute("height", Math.round(s.dataset.h * v));
  });
  document.getElementById("ae-pct").textContent = Math.round(v * 100) + "%";
}
document.getElementById("ae-in").addEventListener("click", () => aeSetZoom(aeZoom() * 1.2));
document.getElementById("ae-out").addEventListener("click", () => aeSetZoom(aeZoom() / 1.2));
document.getElementById("ae-reset").addEventListener("click", () => aeSetZoom(1));

async function loadAutoembed() {
  document.getElementById("ae-pct").textContent = Math.round(aeZoom() * 100) + "%";
  for (const [hostId, file] of Object.entries(AE_FILES)) {
    const host = document.getElementById(hostId);
    if (host.childElementCount) continue;          // ya dibujado
    host.textContent = "Cargando…";
    try {
      const data = await apiJson("/diagrams/" + encodeURIComponent(file));
      renderExcalidraw(data, host);
    } catch (err) { host.textContent = "Error: " + err.message; }
  }
}
