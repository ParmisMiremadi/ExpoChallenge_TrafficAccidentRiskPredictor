/* Small fetch wrapper around the Flask API. Every function returns a promise
   that resolves to parsed JSON, or throws with the server's error message. */

const API = (() => {
  const BASE = "";

  async function get(path) {
    const res = await fetch(BASE + path);
    if (!res.ok) throw new Error(`GET ${path} failed (${res.status})`);
    return res.json();
  }

  async function post(path, body) {
    const res = await fetch(BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `POST ${path} failed (${res.status})`);
    return data;
  }

  return {
    states: () => get("/api/states"),
    counties: (state) => get(`/api/counties?state=${encodeURIComponent(state)}`),
    dangerousZones: (limit = 50) => get(`/api/dangerous-zones?limit=${limit}`),
    stateSummary: () => get("/api/state-summary"),
    seasonTimeRisk: () => get("/api/season-time-risk"),
    alerts: (limit = 100) => get(`/api/alerts?limit=${limit}`),
    dashboardSummary: () => get("/api/dashboard-summary"),
    predict: (payload) => post("/api/predict", payload),
    simulateScenarios: (payload) => post("/api/scenario-simulator", payload),
  };
})();
