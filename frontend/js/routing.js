/* Safe Routing view (prototype). Shows a safest vs fastest route comparison
   on its own Leaflet map. Real version will call a routing engine and rank
   candidate routes by per-segment model risk; here the data is illustrative. */

const Routing = (() => {
  let map = null;
  let lastData = null;
  const layers = [];

  let tileLayer = null;

  function init() {
    if (map) return;
    map = L.map("route-map", { scrollWheelZoom: true }).setView([34.03, -118.36], 11);
    tileLayer = MapTiles.add(map);
    document.addEventListener("themechange", () => {
      tileLayer = MapTiles.swap(map, tileLayer);
    });
  }

  function renderRoutes(data) {
    lastData = data;
    layers.forEach((l) => map.removeLayer(l));
    layers.length = 0;

    const box = document.getElementById("route-options");
    if (!data.options || !data.options.length) {
      box.innerHTML = `<div class="placeholder" style="padding:20px 10px;">${data.error || I18N.t("route.noRoute")}</div>`;
      return;
    }

    const colors = { safest: "#1ea672", fastest: "#d8402f" };
    let bounds = [];

    data.options.forEach((opt) => {
      const line = L.polyline(opt.coords, {
        color: colors[opt.kind] || "#2f5fe0",
        weight: opt.kind === "safest" ? 6 : 4,
        opacity: opt.kind === "safest" ? 0.9 : 0.6,
        dashArray: opt.kind === "fastest" ? "8 6" : null,
      }).addTo(map);
      line.bindPopup(`<b>${opt.label}</b><br/>${opt.minutes} ${I18N.t("route.min")} · ${opt.miles} ${I18N.t("route.mi")}<br/>${I18N.t("route.estProb")}: ${fmt.prob(opt.risk_prob)}`);
      layers.push(line);
      bounds = bounds.concat(opt.coords);
    });

    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] });

    box.innerHTML = data.options
      .sort((a, b) => (a.kind === "safest" ? -1 : 1))
      .map((opt) => `
        <div class="route-option ${opt.kind}">
          <div class="ro-head">
            ${opt.label}
            ${opt.kind === "safest" ? `<span class="tag">${I18N.t("route.recommended")}</span>` : ''}
          </div>
          <div class="ro-meta">
            <span>${opt.minutes} ${I18N.t("route.min")}</span>
            <span>${opt.miles} ${I18N.t("route.mi")}</span>
            <span>${I18N.t("route.risk")} ${fmt.prob(opt.risk_prob)}</span>
          </div>
        </div>
      `).join("");
  }

  async function load() {
    const from = document.getElementById("route-from").value.trim();
    const to = document.getElementById("route-to").value.trim();
    const when = document.getElementById("route-when").value;
    const data = await API.route(from, to, when);
    renderRoutes(data);
  }

  function wire() {
    document.getElementById("btn-route").addEventListener("click", load);
    // Location autocomplete on both endpoints (fills the field; user then
    // clicks "Find safe route").
    Autocomplete.attach(document.getElementById("route-from"), { onSelect: () => {} });
    Autocomplete.attach(document.getElementById("route-to"), { onSelect: () => {} });
    document.addEventListener("langchange", () => {
      if (lastData) renderRoutes(lastData);
    });
  }

  function invalidateSize() {
    if (map) map.invalidateSize();
  }

  return { init, load, wire, invalidateSize };
})();
