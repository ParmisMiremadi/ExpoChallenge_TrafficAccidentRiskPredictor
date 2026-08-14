/* Thin wrapper over Chart.js for the bar charts used in the Forecast view.
   Keeps a handle per canvas id so charts can be redrawn without leaking. */

const Charts = (() => {
  const instances = {};

  const TIER_COLORS = {
    Critical: "#d8402f",
    High: "#e0731f",
    Medium: "#d3960a",
    Low: "#1ea672",
  };

  // Format a probability percentage value plausibly (values are already *100).
  function fmtPct(v) {
    if (v >= 1) return v.toFixed(1) + "%";
    if (v >= 0.01) return v.toFixed(2) + "%";
    return "<0.01%";
  }

  // `values` are probabilities expressed as percentages (prob * 100).
  function bar(canvasId, labels, values, tiers) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    if (instances[canvasId]) instances[canvasId].destroy();

    const colors = (tiers || []).map((t) => TIER_COLORS[t] || "#2f5fe0");

    instances[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: colors.length ? colors : "#2f5fe0",
          borderRadius: 5,
          maxBarThickness: 34,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: { label: (c) => `Est. probability: ${fmtPct(c.parsed.y)}` },
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: "Estimated probability", font: { size: 10 } },
            ticks: { font: { size: 10 }, callback: (v) => v + "%" },
            grid: { color: "#eef0f5" },
          },
          x: { ticks: { font: { size: 10 } }, grid: { display: false } },
        },
      },
    });
  }

  return { bar, TIER_COLORS };
})();
