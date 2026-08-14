/* Risk Forecast view: search a place, then show its predicted risk over the
   next 24 hours and next 7 days, plus the driving factors. This is the
   forward-looking "early warning" surface. */

const Forecast = (() => {

  function render(data) {
    document.getElementById("fc-location").textContent = data.place;
    document.getElementById("fc-peak").textContent =
      `${data.peak.label.toUpperCase()} · ${fmt.prob(data.peak.prob)}`;
    document.getElementById("fc-safe").textContent =
      `${data.safe.label.toUpperCase()} · ${fmt.prob(data.safe.prob)}`;

    Charts.bar(
      "chart-hourly",
      data.hourly.map((h) => h.label),
      data.hourly.map((h) => +(h.prob * 100).toFixed(3)),
      data.hourly.map((h) => h.tier)
    );

    Charts.bar(
      "chart-daily",
      data.daily.map((d) => d.label),
      data.daily.map((d) => +(d.prob * 100).toFixed(3)),
      data.daily.map((d) => d.tier)
    );

    document.getElementById("fc-factors").innerHTML =
      data.factors.map((f) => `<span class="factor-tag">${f}</span>`).join("");
    document.getElementById("fc-tip").textContent = data.tip;
  }

  async function load(place) {
    const data = await API.forecast(place);
    render(data);
  }

  function wire() {
    const input = document.getElementById("forecast-search-input");
    const run = () => load(input.value.trim());
    document.getElementById("btn-forecast").addEventListener("click", run);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") run();
    });
    // Picking a suggestion runs the forecast for that place immediately.
    Autocomplete.attach(input, { onSelect: (it) => load(it.label) });
  }

  return { load, wire };
})();
