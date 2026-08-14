/* Project Overview view: model-performance dashboard.
   Renders Plotly speedometer gauges for each metric, plus a feature-importance
   bar and a calibration (reliability) curve. Everything reads the current CSS
   theme tokens, so it re-renders correctly when dark mode or language changes. */

const Overview = (() => {
  let data = null;      // cached /api/metrics payload
  let loaded = false;

  /* Pull live theme colors from the CSS custom properties so Plotly matches
     light/dark mode without a separate palette. */
  function palette() {
    const cs = getComputedStyle(document.documentElement);
    const v = (n) => cs.getPropertyValue(n).trim();
    return {
      ink: v("--ink"),
      soft: v("--ink-soft"),
      muted: v("--muted"),
      line: v("--line"),
      card: v("--card"),
      blue: v("--blue"),
      green: v("--green"),
      amber: v("--amber"),
      orange: v("--orange"),
      red: v("--red"),
      track: v("--gauge-track") || "#eef0f5",
    };
  }

  /* Map a metric value to a color. For "higher is better" metrics a high value
     is green; for Brier (lower is better) the scale is inverted. */
  function valueColor(value, higherBetter, p) {
    let score = higherBetter ? value : 1 - value;
    if (score >= 0.85) return p.green;
    if (score >= 0.7) return p.blue;
    if (score >= 0.5) return p.amber;
    return p.red;
  }

  function gaugeLayout(p) {
    return {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { t: 10, b: 8, l: 22, r: 22 },
      height: 170,
      font: { color: p.soft, family: "Segoe UI, Roboto, sans-serif" },
    };
  }

  function renderGauge(el, g, p) {
    const color = valueColor(g.value, g.higher_better, p);
    const trace = {
      type: "indicator",
      mode: "gauge+number",
      value: g.value,
      number: {
        font: { size: 30, color: p.ink },
        valueformat: g.value >= 1 ? ".2f" : ".3f",
      },
      gauge: {
        shape: "angular",
        axis: {
          range: [0, 1],
          tickwidth: 1,
          tickcolor: p.muted,
          tickfont: { size: 9, color: p.muted },
          nticks: 6,
        },
        bar: { color: color, thickness: 0.28 },
        bgcolor: "rgba(0,0,0,0)",
        borderwidth: 0,
        steps: [
          { range: [0, 0.5], color: p.track },
          { range: [0.5, 0.75], color: p.track },
          { range: [0.75, 1], color: p.track },
        ],
        threshold: g.baseline != null ? {
          line: { color: p.orange, width: 3 },
          thickness: 0.85,
          value: g.baseline,
        } : undefined,
      },
    };
    Plotly.react(el, [trace], gaugeLayout(p), {
      displayModeBar: false, responsive: true, staticPlot: false,
    });
  }

  function renderGauges(p) {
    const grid = document.getElementById("gauge-grid");
    if (!grid) return;
    grid.innerHTML = "";
    data.gauges.forEach((g) => {
      const cell = document.createElement("div");
      cell.className = "gauge-cell card";
      const plot = document.createElement("div");
      plot.className = "gauge-plot";
      const cap = document.createElement("div");
      cap.className = "gauge-cap";
      const baseline = g.baseline != null
        ? `<span class="gauge-baseline">baseline ${g.baseline.toFixed(3)}</span>` : "";
      cap.innerHTML = `<div class="gauge-name">${g.label}${baseline}</div>
                       <div class="gauge-hint">${g.hint || ""}</div>`;
      cell.appendChild(plot);
      cell.appendChild(cap);
      grid.appendChild(cell);
      renderGauge(plot, g, p);
    });
  }

  function renderHero(p) {
    document.getElementById("ov-model").textContent = data.model_name;
    const d = data.dataset || {};
    const stats = [
      { k: "Train rows", v: (d.n_train || 0).toLocaleString() },
      { k: "Test rows", v: (d.n_test || 0).toLocaleString() },
      { k: "Top-20 county overlap", v: d.top20_overlap || "—" },
    ];
    document.getElementById("ov-hero-stats").innerHTML = stats.map((s) => `
      <div class="ov-hero-stat">
        <div class="ov-hs-v">${s.v}</div>
        <div class="ov-hs-k">${s.k}</div>
      </div>`).join("");
  }

  function renderFeatureImportance(p) {
    const el = document.getElementById("plot-featimp");
    if (!el || !data.feature_importance.length) return;
    const rows = data.feature_importance.slice().reverse();
    const trace = {
      type: "bar",
      orientation: "h",
      y: rows.map((r) => r[0]),
      x: rows.map((r) => r[1]),
      marker: { color: p.orange, line: { width: 0 } },
      hovertemplate: "%{y}: %{x:.3f}<extra></extra>",
    };
    const layout = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { t: 8, b: 30, l: 90, r: 16 },
      height: 300,
      font: { color: p.soft, size: 11 },
      xaxis: { gridcolor: p.line, zerolinecolor: p.line },
      yaxis: { automargin: true },
    };
    Plotly.react(el, [trace], layout, { displayModeBar: false, responsive: true });
  }

  function renderReliability(p) {
    const el = document.getElementById("plot-reliability");
    if (!el || !data.reliability.length) return;
    const pred = data.reliability.map((r) => r[0]);
    const obs = data.reliability.map((r) => r[1]);
    const ideal = {
      x: [0, 1], y: [0, 1], mode: "lines", type: "scatter",
      line: { color: p.muted, dash: "dash", width: 1.5 },
      name: "Ideal", hoverinfo: "skip",
    };
    const curve = {
      x: pred, y: obs, mode: "lines+markers", type: "scatter",
      line: { color: p.blue, width: 2.5 },
      marker: { color: p.blue, size: 7 },
      name: "Model",
      hovertemplate: "pred %{x:.2f} → obs %{y:.2f}<extra></extra>",
    };
    const layout = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      margin: { t: 8, b: 40, l: 44, r: 16 },
      height: 300,
      font: { color: p.soft, size: 11 },
      xaxis: { title: "Predicted", range: [0, 1], gridcolor: p.line, zerolinecolor: p.line },
      yaxis: { title: "Observed", range: [0, 1], gridcolor: p.line, zerolinecolor: p.line },
      showlegend: true,
      legend: { orientation: "h", y: -0.22, font: { size: 10 } },
    };
    Plotly.react(el, [ideal, curve], layout, { displayModeBar: false, responsive: true });
  }

  function renderAll() {
    if (!data || !data.ok) return;
    const p = palette();
    renderHero(p);
    renderGauges(p);
    renderFeatureImportance(p);
    renderReliability(p);
    const note = document.getElementById("ov-note");
    if (note) note.textContent = data.note || "";
  }

  async function load() {
    if (loaded) {
      // Already have data; just make sure Plotly resizes into the now-visible view.
      setTimeout(() => {
        document.querySelectorAll("#view-overview .js-plotly-plot")
          .forEach((el) => Plotly.Plots.resize(el));
      }, 60);
      return;
    }
    try {
      data = await API.metrics();
      loaded = true;
      renderAll();
    } catch (err) {
      const grid = document.getElementById("gauge-grid");
      if (grid) grid.innerHTML = `<div class="placeholder">Could not load metrics.</div>`;
      console.error("Overview load failed:", err);
    }
  }

  function wire() {
    // Re-theme the Plotly charts when the user toggles dark mode.
    document.addEventListener("themechange", () => { if (loaded) renderAll(); });
  }

  return { load, wire };
})();
