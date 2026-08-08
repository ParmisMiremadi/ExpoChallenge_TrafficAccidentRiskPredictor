/* Thin Chart.js wrappers so main.js/predictor.js just pass data in. */

const Charts = (() => {
  const instances = {};

  const BAR_COLOR = "#2f5fe0";
  const GRID_COLOR = "#eef0f5";

  function bar(canvasId, labels, values, { horizontal = false, colors = null, yLabel = "" } = {}) {
    const ctx = document.getElementById(canvasId).getContext("2d");
    if (instances[canvasId]) instances[canvasId].destroy();

    instances[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: colors || BAR_COLOR,
          borderRadius: 5,
          maxBarThickness: 46,
        }],
      },
      options: {
        indexAxis: horizontal ? "y" : "x",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: GRID_COLOR }, ticks: { font: { size: 11 } } },
          y: { grid: { color: GRID_COLOR }, ticks: { font: { size: 11 } }, title: { display: !!yLabel, text: yLabel } },
        },
      },
    });
  }

  return { bar };
})();
