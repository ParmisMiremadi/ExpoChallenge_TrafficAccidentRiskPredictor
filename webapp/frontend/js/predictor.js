/* Everything behind the "Risk Predictor" view: form wiring, the prediction
   result card, and the scenario simulator. */

const Predictor = (() => {
  const stateSelect = () => document.getElementById("in-state");
  const countySelect = () => document.getElementById("in-county");
  const hourInput = () => document.getElementById("in-hour");

  function timePeriodFor(hour) {
    if (hour >= 5 && hour < 9) return "Morning Peak";
    if (hour >= 9 && hour < 12) return "Morning";
    if (hour >= 12 && hour < 16) return "Afternoon";
    if (hour >= 16 && hour < 20) return "Evening Peak";
    if (hour >= 20 && hour < 24) return "Night";
    return "Late Night";
  }

  function formatHour(h) {
    const period = h < 12 ? "AM" : "PM";
    const displayHour = h % 12 === 0 ? 12 : h % 12;
    return `${displayHour}:00 ${period}`;
  }

  async function populateStates() {
    const states = await API.states();
    const select = stateSelect();
    select.innerHTML = states.map((s) => `<option value="${s}">${s}</option>`).join("");
    select.value = states.includes("CA") ? "CA" : states[0];
    await populateCounties();
  }

  async function populateCounties() {
    const state = stateSelect().value;
    const counties = await API.counties(state);
    const select = countySelect();
    select.innerHTML = counties.map((c) => `<option value="${c}">${c}</option>`).join("");
    if (counties.includes("Los Angeles")) select.value = "Los Angeles";
  }

  function readForm() {
    const hour = parseInt(hourInput().value, 10);
    return {
      state: stateSelect().value,
      county: countySelect().value,
      season: document.getElementById("in-season").value,
      hour,
      is_weekend: document.getElementById("in-weekend").checked,
      crossing: document.getElementById("in-crossing").checked,
      junction: document.getElementById("in-junction").checked,
      traffic_signal: document.getElementById("in-traffic-signal").checked,
      stop: document.getElementById("in-stop").checked,
      station: document.getElementById("in-station").checked,
      amenity: document.getElementById("in-amenity").checked,
    };
  }

  function tierClass(alertLevel) {
    if (alertLevel === "Critical Alert") return "critical";
    if (alertLevel === "High Alert") return "high";
    if (alertLevel === "Medium Alert") return "medium";
    return "low";
  }

  function gaugeColor(score) {
    if (score >= 80) return "#1ea672";
    if (score >= 60) return "#3f8f4f";
    if (score >= 40) return "#d3960a";
    if (score >= 20) return "#e0731f";
    return "#d8402f";
  }

  function renderResult(result) {
    const card = document.getElementById("result-card");
    const tier = tierClass(result.alert_level);
    const color = gaugeColor(result.safety_score);

    card.innerHTML = `
      <div class="result-top">
        <div class="gauge" style="--gauge-pct:${result.safety_score};--gauge-color:${color}">
          <div class="gauge-inner">
            <div class="num" style="color:${color}">${result.safety_score}</div>
            <div class="unit">SAFETY SCORE</div>
          </div>
        </div>
        <div class="result-meta">
          <div class="loc">${result.county}, ${result.state}</div>
          <div class="row"><span class="k">Risk probability</span><strong>${result.risk_probability_pct}%</strong></div>
          <div class="row"><span class="k">Predicted label</span><strong>${result.predicted_high_risk ? "High Risk" : "Low Risk"}</strong></div>
          <div class="row"><span class="k">Alert level</span><span class="badge ${tier}">${result.alert_level}</span></div>
          <div class="row"><span class="k">Time period</span><strong>${result.time_period}</strong></div>
          <div class="row"><span class="k">Safety status</span><strong>${result.safety_status}</strong></div>
        </div>
      </div>
      <div class="recommendation-box">
        <b>Prevention recommendation:</b> ${result.prevention_recommendation}
      </div>
    `;
  }

  function renderScenarios(data) {
    const card = document.getElementById("scenario-card");
    card.style.display = "block";

    const labels = data.scenarios.map((s) => s.scenario);
    const values = data.scenarios.map((s) => s.risk_probability_pct);
    const colors = data.scenarios.map((s) =>
      s.scenario === data.best_improvement.best_scenario ? "#1ea672" : "#2f5fe0"
    );
    Charts.bar("chart-scenarios", labels, values, { colors, yLabel: "Risk probability (%)" });

    const imp = data.best_improvement;
    document.getElementById("best-improvement-box").innerHTML = `
      <b>Best improvement recommendation:</b>
      Switching to "<b>${imp.best_scenario}</b>" would take predicted risk from
      ${imp.current_risk_pct}% to ${imp.improved_risk_pct}%
      (&minus;${imp.risk_reduction_pts} pts, ${imp.improvement_rate_pct}% relative reduction).
      Priority: <b>${imp.priority}</b>. Action: ${imp.recommended_action}
    `;
  }

  function wire() {
    stateSelect().addEventListener("change", populateCounties);

    hourInput().addEventListener("input", () => {
      const hour = parseInt(hourInput().value, 10);
      document.getElementById("hour-value").textContent = formatHour(hour);
      document.getElementById("time-period-readout").textContent = timePeriodFor(hour);
    });

    document.getElementById("btn-predict").addEventListener("click", async () => {
      const btn = document.getElementById("btn-predict");
      btn.disabled = true;
      btn.textContent = "Predicting…";
      try {
        const result = await API.predict(readForm());
        renderResult(result);
      } catch (err) {
        document.getElementById("result-card").innerHTML =
          `<div class="placeholder">${err.message}</div>`;
      } finally {
        btn.disabled = false;
        btn.textContent = "Predict Risk";
      }
    });

    document.getElementById("btn-simulate").addEventListener("click", async () => {
      const btn = document.getElementById("btn-simulate");
      btn.disabled = true;
      btn.textContent = "Simulating…";
      try {
        const data = await API.simulateScenarios(readForm());
        renderScenarios(data);
      } catch (err) {
        alert(err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = "Run Scenario Simulator";
      }
    });
  }

  async function init() {
    await populateStates();
    wire();
    document.getElementById("in-hour").dispatchEvent(new Event("input"));
  }

  return { init };
})();
