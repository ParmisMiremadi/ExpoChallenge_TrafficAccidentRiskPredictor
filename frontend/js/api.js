/* Small fetch wrapper around the Flask API. Every function returns a promise
   that resolves to parsed JSON, or throws with the server's error message. */

/* Display formatters shared across views. `prob` renders a calibrated absolute
   probability plausibly; `x` renders a "N x national average" multiple. */
window.fmt = {
  prob(p) {
    const pct = p * 100;
    if (pct >= 1) return pct.toFixed(1) + "%";
    if (pct >= 0.01) return pct.toFixed(2) + "%";
    return "<0.01%";
  },
  x(v) {
    return (v >= 1 ? Math.round(v) : v.toFixed(1)) + "×";
  },
};

const API = (() => {
  const BASE = "";

  async function get(path) {
    const res = await fetch(BASE + path);
    if (!res.ok) throw new Error(`GET ${path} failed (${res.status})`);
    return res.json();
  }

  const qs = (obj) =>
    Object.entries(obj)
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join("&");

  return {
    meta: () => get("/api/meta"),
    news: () => get("/api/news"),
    weather: (lat, lng) => get(`/api/weather?${qs({ lat, lng })}`),
    riskMap: (hour, metric, level) => get(`/api/risk-map?${qs({ hour, metric, level })}`),
    statesGeo: () => get("/data/us-states.geojson"),
    roadsGeo: () => get("/data/primary_roads.geojson"),
    zones: (hour, tier) => get(`/api/zones?${qs({ hour, tier })}`),
    forecast: (place) => get(`/api/forecast?${qs({ place })}`),
    route: (from, to, when) => get(`/api/route?${qs({ from, to, when })}`),
  };
})();
