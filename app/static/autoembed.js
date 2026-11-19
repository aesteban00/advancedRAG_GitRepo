/* autoembed.js - pestaña "¿Por qué Autoembedding?": muestra los dos esquemas como imagen (SVG).
   Cada panel se pliega/despliega por separado y tiene su propia barra de scroll. Zoom compartido. */
const AE_ZOOM = { key: "ae_zoom", def: 0.5, min: 0.2, max: 2 };
const AE_IMAGES = { "ae-con": "arch_CON_autoembedding.png", "ae-sin": "arch_SIN_autoembedding.jpeg" };

function aeZoom() {
  const v = parseFloat(localStorage.getItem(AE_ZOOM.key));
  return isFinite(v) ? Math.min(AE_ZOOM.max, Math.max(AE_ZOOM.min, v)) : AE_ZOOM.def;
}
// Aplica el zoom a las imágenes: ancho natural x zoom (la altura sigue la proporción).
function aeApplyZoom() {
  const v = aeZoom();
  document.querySelectorAll("#view-autoembed img.ae-img").forEach((img) => {
    if (img.naturalWidth) img.style.width = Math.round(img.naturalWidth * v) + "px";
  });
  document.getElementById("ae-pct").textContent = Math.round(v * 100) + "%";
}
function aeSetZoom(z) {
  localStorage.setItem(AE_ZOOM.key, String(Math.min(AE_ZOOM.max, Math.max(AE_ZOOM.min, Math.round(z * 100) / 100))));
  aeApplyZoom();
}
document.getElementById("ae-in").addEventListener("click", () => aeSetZoom(aeZoom() * 1.2));
document.getElementById("ae-out").addEventListener("click", () => aeSetZoom(aeZoom() / 1.2));
document.getElementById("ae-reset").addEventListener("click", () => aeSetZoom(1));

// Carga las imágenes una sola vez (al entrar en la pestaña).
function loadAutoembed() {
  for (const [hostId, file] of Object.entries(AE_IMAGES)) {
    const host = document.getElementById(hostId);
    if (host.querySelector("img")) continue;
    const img = document.createElement("img");
    img.className = "ae-img";
    img.alt = file;
    img.addEventListener("load", aeApplyZoom);
    img.addEventListener("error", () => { host.textContent = "No se pudo cargar " + file + " (¿está en interna/esquemas/?)"; });
    img.src = "/diagrams/" + encodeURIComponent(file);
    host.appendChild(img);
  }
  aeApplyZoom();
}

// Reparto del alto: un panel plegado ocupa solo su titulo; el desplegado toma el resto.
function aeLayout() {
  document.querySelectorAll("#view-autoembed .ae-fold").forEach((d) => {
    d.parentElement.classList.toggle("is-closed", !d.open);
  });
}
document.querySelectorAll("#view-autoembed .ae-fold").forEach((d) => d.addEventListener("toggle", aeLayout));
aeLayout();
