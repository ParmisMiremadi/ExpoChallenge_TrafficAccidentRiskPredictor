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

  // County level-of-detail: in the State view, at or beyond this zoom we swap
  // the state choropleth for a per-county one (each county scored separately).
  const COUNTY_DETAIL_ZOOM = 6;
  let countyGeo = null;        // cached us-counties GeoJSON
  let countyLayer = null;      // county choropleth layer (built once, restyled)
  let countyData = null;       // last-fetched {"ST|County": {...}} scores
  let countyKey = "";          // hour|metric of countyData (cache guard)
  let countyLoading = false;
  // Current State-view context so zoom changes can refresh the right layer.
  const stateCtx = { active: false, hour: 0, metric: "risk" };

  // US state FIPS code (as used in the counties GeoJSON `STATE` field) -> abbr.
  const FIPS_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
  };

  // Join key from a county GeoJSON feature -> backend "ST|County" key.
  function countyKeyOf(feature) {
    const abbr = FIPS_ABBR[feature.properties.STATE];
    return abbr ? `${abbr}|${feature.properties.NAME}` : null;
  }

  // --- interpolation for counties the model doesn't directly cover --------- #
  let countyCentroids = null;   // feature id -> [lng, lat] (bbox center)
  let countyNeighbors = null;   // unmatched id -> [matched "ST|County" keys]
  let countyInterp = null;      // unmatched id -> {prob, severity, tier, interpolated}
  const INTERP_K = 4;
  const TIER_RANK = { Low: 0, Medium: 1, High: 2, Critical: 3 };
  const RANK_TIER = ["Low", "Medium", "High", "Critical"];

  function featureCentroid(feature) {
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    const walk = (coords) => {
      if (typeof coords[0] === "number") {
        if (coords[0] < minx) minx = coords[0];
        if (coords[0] > maxx) maxx = coords[0];
        if (coords[1] < miny) miny = coords[1];
        if (coords[1] > maxy) maxy = coords[1];
      } else {
        for (const c of coords) walk(c);
      }
    };
    walk(feature.geometry.coordinates);
    return [(minx + maxx) / 2, (miny + maxy) / 2];
  }

  /* Precompute, once, the k nearest data-carrying counties for each FIPS-mapped
     county that has no model data. Which counties have data is constant across
     hours, so only this mapping is cached; the values are filled per refresh. */
  function buildCountyNeighbors() {
    if (countyNeighbors) return;
    countyCentroids = {};
    const matched = [];
    const unmatched = [];
    for (const f of countyGeo.features) {
      const c = featureCentroid(f);
      countyCentroids[f.id] = c;
      const key = countyKeyOf(f);
      if (!key) continue;                       // territory outside model scope
      if (countyData[key]) matched.push({ key, c });
      else unmatched.push({ id: f.id, c });
    }
    countyNeighbors = {};
    for (const u of unmatched) {
      const near = matched
        .map((m) => {
          const dx = m.c[0] - u.c[0], dy = m.c[1] - u.c[1];
          return [dx * dx + dy * dy, m.key];
        })
        .sort((a, b) => a[0] - b[0])
        .slice(0, INTERP_K)
        .map((x) => x[1]);
      countyNeighbors[u.id] = near;
    }
  }

  /* Fill each no-data county from the mean of its nearest neighbors' current
     risk/severity, with a tier from the rounded mean neighbor tier. */
  function computeCountyInterp() {
    buildCountyNeighbors();
    countyInterp = {};
    for (const id in countyNeighbors) {
      let sp = 0, ss = 0, rank = 0, n = 0;
      for (const key of countyNeighbors[id]) {
        const d = countyData[key];
        if (!d) continue;
        sp += d.prob; ss += d.severity; rank += TIER_RANK[d.tier] ?? 1; n++;
      }
      if (!n) continue;
      countyInterp[id] = {
        prob: sp / n,
        severity: ss / n,
        tier: RANK_TIER[Math.round(rank / n)] || "Medium",
        interpolated: true,
      };
    }
  }

  // County data (direct if scored, else interpolated from neighbors).
  function countyEntry(feature) {
    const d = countyData ? countyData[countyKeyOf(feature)] : null;
    if (d) return d;
    return countyInterp ? countyInterp[feature.id] : null;
  }

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

  let tileLayer = null;

  function init() {
    if (map) return;
    // preferCanvas keeps the large primary-road layer performant.
    // scrollWheelZoom lets users zoom with the mouse wheel (more natural than
    // the +/- buttons).
    map = L.map("map", { scrollWheelZoom: true, zoomControl: true, preferCanvas: true })
      .setView([39.5, -98.3], 4);
    tileLayer = MapTiles.add(map);

    // Swap to light/dark basemap tiles when the theme toggles.
    document.addEventListener("themechange", () => {
      tileLayer = MapTiles.swap(map, tileLayer);
    });

    // Re-draw the road layer when crossing the detail threshold.
    map.on("zoomend", () => {
      if (roadCtx.active) {
        const major = map.getZoom() < ROAD_DETAIL_ZOOM;
        if (major !== roadCtx.major) drawRoads();
      }
      // In the State view, swap state <-> county detail across the threshold.
      if (stateCtx.active) syncStateLod();
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
    if (!s) return `<div class="popup-title">${name}</div><div>${I18N.t("popup.noData")}</div>`;
    const cls = s.tier.toLowerCase();
    const line = metric === "severity"
      ? `${I18N.t("popup.avgSeverity")}: <span class="popup-risk ${cls}">${s.severity.toFixed(1)} / 4</span>`
      : `${I18N.t("popup.risk")}: <span class="popup-risk ${cls}">${I18N.t("tier." + s.tier)}</span><br/>` +
        `${I18N.t("popup.estProb")}: ${fmt.prob(s.prob)}`;
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

  async function renderStates(statesData, metric, hour) {
    await ensureGeo();
    roadCtx.active = false;
    stateCtx.active = true;
    stateCtx.metric = metric;
    if (typeof hour === "number") stateCtx.hour = hour;

    if (roadLayer && map.hasLayer(roadLayer)) map.removeLayer(roadLayer);

    // Build the state layer once; afterwards only re-style + re-bind popups so
    // the hour slider and metric toggle update smoothly.
    if (!stateLayer) {
      stateLayer = L.geoJSON(geo, {
        style: (feature) => styleFor(statesData[feature.properties.name]),
        onEachFeature: (feature, layer) => {
          layer.on({
            mouseover: (e) => e.target.setStyle({ weight: 2.5, color: "#16202e" }),
            mouseout: (e) => e.target.setStyle({ weight: 1, color: "#ffffff" }),
            // Zoom past the county threshold so clicking a state reveals its counties.
            click: (e) => map.fitBounds(e.target.getBounds(), { maxZoom: 7 }),
          });
        },
      });
    }

    stateLayer.eachLayer((layer) => {
      const name = layer.feature.properties.name;
      const s = statesData[name];
      layer.setStyle(styleFor(s));
      layer.bindPopup(statePopup(name, s, metric));
    });

    // Decide which layer to show for the current zoom (state vs. county detail).
    await syncStateLod();
  }

  /* Show the state choropleth zoomed out, the county choropleth zoomed in. */
  async function syncStateLod() {
    if (!stateCtx.active) return;
    if (map.getZoom() >= COUNTY_DETAIL_ZOOM) {
      await showCounties();
    } else {
      if (countyLayer && map.hasLayer(countyLayer)) map.removeLayer(countyLayer);
      if (stateLayer && !map.hasLayer(stateLayer)) stateLayer.addTo(map);
    }
  }

  function styleCounty(feature) {
    const e = countyEntry(feature);
    if (!e) {
      // No data and no neighbors to interpolate from: faint outline only.
      return { fillColor: "#c7cede", fillOpacity: 0.12, color: "#ffffff", weight: 0.25 };
    }
    return {
      fillColor: TIER_COLORS[e.tier] || TIER_COLORS.None,
      // Interpolated counties are drawn slightly softer than directly-scored ones.
      fillOpacity: e.interpolated ? 0.55 : 0.74,
      color: "#ffffff",
      weight: 0.4,
    };
  }

  function countyPopup(feature) {
    const abbr = FIPS_ABBR[feature.properties.STATE] || "";
    const name = abbr ? `${feature.properties.NAME}, ${abbr}` : feature.properties.NAME;
    const e = countyEntry(feature);
    let html = statePopup(name, e, stateCtx.metric);
    if (e && e.interpolated) {
      html += `<div class="popup-why">${I18N.t("popup.interp")}</div>`;
    }
    return html;
  }

  async function showCounties() {
    const key = `${stateCtx.hour}|${stateCtx.metric}`;

    // (Re)fetch county geometry + scores when missing or the hour/metric changed.
    if (!countyGeo || countyKey !== key) {
      if (countyLoading) return;   // a fetch is in flight; it will restyle on finish
      countyLoading = true;
      try {
        if (!countyGeo) countyGeo = await API.countiesGeo();
        const resp = await API.riskMap(stateCtx.hour, stateCtx.metric, "county");
        countyData = resp.counties || {};
        countyKey = key;
        computeCountyInterp();   // fill no-data counties from neighbors
      } finally {
        countyLoading = false;
      }
      // Bailed out of county zoom (or view) while awaiting? Don't force it back.
      if (!stateCtx.active || map.getZoom() < COUNTY_DETAIL_ZOOM) return;
    }

    if (!countyLayer) {
      countyLayer = L.geoJSON(countyGeo, {
        style: (f) => styleCounty(f),
        onEachFeature: (f, layer) => {
          layer.bindPopup(() => countyPopup(layer.feature));
          layer.on({
            mouseover: (e) => e.target.setStyle({ weight: 1.6, color: "#16202e" }),
            mouseout: (e) => e.target.setStyle(styleCounty(e.target.feature)),
          });
        },
      });
    }

    countyLayer.setStyle(styleCounty);
    if (stateLayer && map.hasLayer(stateLayer)) map.removeLayer(stateLayer);
    if (!map.hasLayer(countyLayer)) countyLayer.addTo(map);
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
    // Leaving the State view: drop its county overlay too.
    stateCtx.active = false;
    if (countyLayer && map.hasLayer(countyLayer)) map.removeLayer(countyLayer);
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

  // Fly to a coordinate and zoom in far enough to reveal county detail.
  function flyTo(lat, lng, zoom) {
    if (map) map.setView([lat, lng], zoom || 8);
  }

  function invalidateSize() {
    if (map) map.invalidateSize();
  }

  return { init, renderStates, renderRoadsGeo, flyToState, flyTo, invalidateSize };
})();
