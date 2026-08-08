/* App bootstrap: nav switching + loading every "read-only" panel
   (map, sidebar widgets, forecast charts, reports table) from the
   precomputed API endpoints. The Risk Predictor view is handled by
   predictor.js since it talks to the live-prediction endpoints instead. */

function tierClass(alertLevel) {
  if (alertLevel === "Critical Alert" || alertLevel === "Critical") return "critical";
  if (alertLevel === "High Alert" || alertLevel === "High") return "high";
  if (alertLevel === "Medium Alert" || alertLevel === "Medium") return "medium";
  return "low";
}

function switchView(name) {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${name}`);
  });
  if (name === "map") {
    // Leaflet needs a visible container to size itself correctly the first
    // time its tab becomes visible.
    setTimeout(() => RiskMap.invalidateSize(), 50);
  }
}

function wireNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
}

async function loadSidebarFooter() {
  const summary = await API.dashboardSummary();
  document.getElementById("footer-model").textContent = summary.model_name;
  document.getElementById("footer-threshold").textContent = summary.decision_threshold;

  document.getElementById("stat-total").textContent = summary.total_records.toLocaleString();
  document.getElementById("stat-high-risk").textContent =
    `${summary.predicted_high_risk.toLocaleString()} (${summary.predicted_high_risk_pct.toFixed(1)}%)`;
  document.getElementById("stat-critical").textContent = summary.alert_counts["Critical Alert"].toLocaleString();
  document.getElementById("stat-top-zone").textContent =
    `${summary.top_zone.county}, ${summary.top_zone.state}`;
}

async function loadSidebarAlerts() {
  const alerts = await API.alerts(5);
  const box = document.getElementById("sidebar-alerts");
  if (!alerts.length) {
    box.innerHTML = `<div class="alert-row"><small>No active alerts.</small></div>`;
    return;
  }
  box.innerHTML = alerts.map((a) => `
    <div class="alert-row">
      <div class="dot ${tierClass(a.Alert_Level)}"></div>
      <div>
        <strong>${a.County}, ${a.State}</strong>
        <small>${a.Alert_Level} · ${a.Time_Period}, ${a.Season}</small>
      </div>
    </div>
  `).join("");
}

async function loadMap() {
  RiskMap.init();
  const states = await API.stateSummary();
  RiskMap.render(states);
}

async function loadZonesTable() {
  const zones = await API.dangerousZones(15);
  const body = document.getElementById("zones-table-body");
  body.innerHTML = zones.map((z) => `
    <tr>
      <td>${z.State}</td>
      <td>${z.County}</td>
      <td><span class="badge ${tierClass(z.Risk_Level)}">${z.Risk_Level}</span></td>
      <td>${z.Risk_Score.toFixed(1)}</td>
      <td>${z.High_Risk_Count} / ${z.Total_Records}</td>
      <td>${z.Recommended_Action}</td>
    </tr>
  `).join("");
}

async function loadSidebarForecast() {
  const data = await API.seasonTimeRisk();
  const byTime = data.by_time_period;
  const max = Math.max(...byTime.map((t) => t.High_Risk_Percentage));

  const order = ["Morning Peak", "Morning", "Afternoon", "Evening Peak", "Night", "Late Night"];
  const sorted = [...byTime].sort((a, b) => order.indexOf(a.Time_Period) - order.indexOf(b.Time_Period));

  const bars = document.getElementById("sidebar-forecast-bars");
  bars.innerHTML = sorted.map((t) => {
    const pct = Math.max(8, (t.High_Risk_Percentage / max) * 100);
    const isPeak = t.High_Risk_Percentage === max;
    return `<div class="bar ${isPeak ? "peak" : ""}" style="height:${pct}%" title="${t.Time_Period}: ${t.High_Risk_Percentage.toFixed(1)}%"></div>`;
  }).join("");

  const safest = [...byTime].sort((a, b) => a.High_Risk_Percentage - b.High_Risk_Percentage)[0];
  document.getElementById("safest-window-tag").textContent = safest.Time_Period.split(" ")[0];
  document.getElementById("safest-window-title").textContent = `Safest window: ${safest.Time_Period}`;
  document.getElementById("safest-window-sub").textContent =
    `${safest.High_Risk_Percentage.toFixed(1)}% high-risk rate`;
}

async function loadForecastView() {
  const data = await API.seasonTimeRisk();

  Charts.bar(
    "chart-season",
    data.by_season.map((s) => s.Season),
    data.by_season.map((s) => Number(s.High_Risk_Percentage.toFixed(2))),
    { colors: "#2f5fe0" }
  );

  const order = ["Morning Peak", "Morning", "Afternoon", "Evening Peak", "Night", "Late Night"];
  const byTime = [...data.by_time_period].sort(
    (a, b) => order.indexOf(a.Time_Period) - order.indexOf(b.Time_Period)
  );
  Charts.bar(
    "chart-time",
    byTime.map((t) => t.Time_Period),
    byTime.map((t) => Number(t.High_Risk_Percentage.toFixed(2))),
    { colors: "#2f5fe0" }
  );

  const months = data.months_covered.length;
  document.getElementById("forecast-note").textContent =
    `The 2023 evaluation window only covers ${months} calendar month(s), so only the seasons ` +
    `present in that window are shown above. The chart updates automatically as later months are added.`;
}

async function loadReportsView(filterTier = "all") {
  const alerts = await API.alerts(300); // enough to cover all three alert tiers, not just the highest-probability rows
  const filtered = filterTier === "all" ? alerts : alerts.filter((a) => a.Alert_Level === filterTier);

  const body = document.getElementById("reports-table-body");
  if (!filtered.length) {
    body.innerHTML = `<tr class="loading-row"><td colspan="6">No alerts at this tier.</td></tr>`;
    return;
  }
  body.innerHTML = filtered.slice(0, 60).map((a) => `
    <tr>
      <td>${a.County}, ${a.State}</td>
      <td>${a.Season}</td>
      <td>${a.Time_Period}</td>
      <td><span class="badge ${tierClass(a.Alert_Level)}">${a.Alert_Level}</span></td>
      <td class="report-message">${a.Safety_Alert}</td>
      <td class="report-actions">${a.Prevention_Recommendation}</td>
    </tr>
  `).join("");
}

function wireReportFilters() {
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      loadReportsView(chip.dataset.tier);
    });
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  wireNav();
  wireReportFilters();

  try {
    await Promise.all([
      loadSidebarFooter(),
      loadSidebarAlerts(),
      loadSidebarForecast(),
      loadMap(),
      loadZonesTable(),
      loadForecastView(),
      loadReportsView(),
      Predictor.init(),
    ]);
  } catch (err) {
    console.error("Failed to initialize dashboard:", err);
  }
});
