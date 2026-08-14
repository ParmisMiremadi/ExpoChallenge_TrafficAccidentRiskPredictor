/* Leaflet map of live predicted risk.

   State view (default): a choropleth of all US states, each polygon shaded by
   its average risk (or severity) for the selected hour. Road view: the primary
   road network colored by risk (wired; renders once the road layer is added).
   The map re-renders whenever the hour slider, Risk/Severity, or State/Road
   toggle changes. */

const RiskMap = (() => {
  let map = null;
  let geo = null;          // cached us-states GeoJSON
  let roadsGeo = null;     // cached primary-roads GeoJSON
  let stateLayer = null;   // current choropleth layer
  let roadLayer = null;    // current road layer

  // Road level-of-detail: below this zoom show only the major long-distance
  // network (Interstates + US highways); zoom in for the full network.
  const ROAD_DETAIL_ZOOM = 6;
  const MAJOR_TYPES = new Set(["I", "U"]);
  const roadCtx = { active: false, hour: 0, metric: "risk", major: null };

  const TIER_COLORS = {
    Critical: "#d8402f",
    High: "#e0731f",
    Medium: "#d3960a",
    Low: "#1ea672",
    None: "#c7cede",
  };

  // Diurnal risk multiplier by hour, mirroring the backend's DIURNAL profile
  // so road coloring reacts to the hour slider without a per-road server call.
  const DIURNAL = [
    0.35, 0.28, 0.24, 0.24, 0.30, 0.45,
    0.70, 0.95, 1.00, 0.85, 0.70, 0.72,
    0.78, 0.80, 0.82, 0.90, 1.00, 1.05,
    0.98, 0.80, 0.65, 0.55, 0.48, 0.40,
  ];

  function tierFromRisk(r) {
    if (r >= 0.80) return "Critical";
    if (r >= 0.60) return "High";
    if (r >= 0.35) return "Medium";
    return "Low";
  }

  function init() {
    if (map) return;
    // preferCanvas keeps the large primary-road layer performant.
    map = L.map("map", { scrollWheelZoom: false, zoomControl: true, preferCanvas: true })
      .setView([39.5, -98.3], 4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    // Re-draw the road layer when crossing the detail threshold.
    map.on("zoomend", () => {
      if (!roadCtx.active) return;
      const major = map.getZoom() < ROAD_DETAIL_ZOOM;
      if (major !== roadCtx.major) drawRoads();
    });
  }

  async function ensureGeo() {
    if (!geo) geo = await API.statesGeo();
    return geo;
  }

  function detachStates() {
    if (stateLayer && map.hasLayer(stateLayer)) map.removeLayer(stateLayer);
  }

  function statePopup(name, s, metric) {
    if (!s) return `<div class="popup-title">${name}</div><div>No data</div>`;
    const cls = s.tier.toLowerCase();
    const line = metric === "severity"
      ? `Avg severity: <span class="popup-risk ${cls}">${s.severity.toFixed(1)} / 4</span>`
      : `Risk: <span class="popup-risk ${cls}">${s.tier}</span><br/>` +
        `Est. probability: ${fmt.prob(s.prob)}`;
    return `<div class="popup-title">${name}</div><div>${line}</div>`;
  }

  function styleFor(s) {
    return {
      fillColor: TIER_COLORS[s ? s.tier : "None"],
      fillOpacity: 0.72,
      color: "#ffffff",
      weight: 1,
    };
  }

  async function renderStates(statesData, metric) {
    await ensureGeo();
    roadCtx.active = false;

    // Build the layer once; afterwards only re-style + re-bind popups so the
    // hour slider and metric toggle update smoothly without rebuilding 52 polygons.
    if (roadLayer && map.hasLayer(roadLayer)) map.removeLayer(roadLayer);

    if (!stateLayer) {
      stateLayer = L.geoJSON(geo, {
        style: (feature) => styleFor(statesData[feature.properties.name]),
        onEachFeature: (feature, layer) => {
          layer.on({
            mouseover: (e) => e.target.setStyle({ weight: 2.5, color: "#16202e" }),
            mouseout: (e) => e.target.setStyle({ weight: 1, color: "#ffffff" }),
            click: (e) => map.fitBounds(e.target.getBounds(), { maxZoom: 6 }),
          });
        },
      }).addTo(map);
    } else if (!map.hasLayer(stateLayer)) {
      stateLayer.addTo(map);
    }

    stateLayer.eachLayer((layer) => {
      const name = layer.feature.properties.name;
      const s = statesData[name];
      layer.setStyle(styleFor(s));
      layer.bindPopup(statePopup(name, s, metric));
    });
  }

  function drawRoads() {
    if (!roadsGeo || !roadCtx.tiers) return;
    const major = map.getZoom() < ROAD_DETAIL_ZOOM;
    roadCtx.major = major;
    if (roadLayer) map.removeLayer(roadLayer);
    roadLayer = L.geoJSON(roadsGeo, {
      filter: (f) => (major ? MAJOR_TYPES.has(f.properties.rttyp) : true),
      style: (f) => ({
        color: TIER_COLORS[roadCtx.tiers[f.properties._i]] || "#888",
        weight: 1.6,
        opacity: 0.8,
      }),
    }).addTo(map);
  }

  async function renderRoadsGeo(hour, metric) {
    detachStates();
    if (!roadsGeo) {
      roadsGeo = await API.roadsGeo();
      roadsGeo.features.forEach((f, i) => { f.properties._i = i; });
    }
    // Real per-segment risk tiers from the model, aligned to feature order.
    const data = await API.riskMap(hour, metric, "road");
    roadCtx.active = true;
    roadCtx.hour = hour;
    roadCtx.metric = metric;
    roadCtx.tiers = data.tiers;
    drawRoads();
    return data.summary;
  }

  function flyToState(name) {
    if (!stateLayer) return false;
    let found = false;
    stateLayer.eachLayer((layer) => {
      if (layer.feature.properties.name.toLowerCase().includes(name.toLowerCase())) {
        map.fitBounds(layer.getBounds(), { maxZoom: 6 });
        layer.openPopup();
        found = true;
      }
    });
    return found;
  }

  function invalidateSize() {
    if (map) map.invalidateSize();
  }

  return { init, renderStates, renderRoadsGeo, flyToState, invalidateSize };
})();
