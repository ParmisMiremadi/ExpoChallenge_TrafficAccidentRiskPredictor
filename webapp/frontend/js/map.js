/* Leaflet map of state-level predicted risk. The model's own Start_Lat /
   Start_Lng columns are standardized (not real degrees -- see the notebook's
   section 2 note), so markers are placed on real US state centroids instead
   and colored/sized from the state's aggregated Risk_Score. */

const RiskMap = (() => {
  let map = null;
  const markers = [];

  const TIER_COLORS = {
    Critical: "#d8402f",
    High: "#e0731f",
    Medium: "#d3960a",
    Low: "#1ea672",
  };

  function init() {
    // Scroll-zoom is off on purpose: an embedded dashboard map shouldn't
    // hijack the page's scroll wheel. Drag-to-pan and the +/- buttons
    // still work normally.
    map = L.map("map", { scrollWheelZoom: false }).setView([39.5, -98.3], 4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 10,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
  }

  function tierFromScore(score, breakpoints) {
    if (score >= breakpoints.p90) return "Critical";
    if (score >= breakpoints.p75) return "High";
    if (score >= breakpoints.p50) return "Medium";
    return "Low";
  }

  function quantile(sorted, q) {
    const pos = (sorted.length - 1) * q;
    const base = Math.floor(pos);
    const rest = pos - base;
    if (sorted[base + 1] !== undefined) {
      return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
    }
    return sorted[base];
  }

  function render(states) {
    markers.forEach((m) => map.removeLayer(m));
    markers.length = 0;

    const scores = states.map((s) => s.Avg_Risk_Score).sort((a, b) => a - b);
    const breakpoints = {
      p50: quantile(scores, 0.5),
      p75: quantile(scores, 0.75),
      p90: quantile(scores, 0.9),
    };

    states.forEach((s) => {
      const tier = tierFromScore(s.Avg_Risk_Score, breakpoints);
      const radius = 7 + Math.min(18, Math.sqrt(s.County_Count) * 2.4);

      const marker = L.circleMarker([s.Lat, s.Lng], {
        radius,
        color: TIER_COLORS[tier],
        fillColor: TIER_COLORS[tier],
        fillOpacity: 0.55,
        weight: 2,
      }).addTo(map);

      marker.bindPopup(`
        <strong>${s.State}</strong> &mdash; ${tier} risk<br/>
        Counties evaluated: ${s.County_Count}<br/>
        Critical counties: ${s.Critical_County_Count}<br/>
        Top county: ${s.Top_County} (${s.Top_County_Risk_Level})
      `);

      markers.push(marker);
    });
  }

  function invalidateSize() {
    if (map) map.invalidateSize();
  }

  return { init, render, invalidateSize };
})();
