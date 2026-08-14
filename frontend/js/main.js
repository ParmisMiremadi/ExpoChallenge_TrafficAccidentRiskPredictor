/* App bootstrap: nav switching + wiring the Live Risk Map controls (hour
   slider, Risk/Severity toggle, search) and loading each view. Data comes
   from the API endpoints in api.js. */

const State = {
  hour: new Date().getHours(),
  metric: "risk",
  level: "state",
  points: [],
};

// Monotonic token so a slow earlier response can't overwrite a newer one.
let mapReqSeq = 0;

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */
function formatHour(h) {
  const ampm = h < 12 ? "AM" : "PM";
  let hr = h % 12;
  if (hr === 0) hr = 12;
  return `${hr}:00 ${ampm}`;
}

function timePeriod(h) {
  if (h >= 6 && h <= 8) return "Morning Peak";
  if (h >= 9 && h <= 11) return "Midday";
  if (h >= 12 && h <= 15) return "Afternoon";
  if (h >= 16 && h <= 18) return "Evening Peak";
  if (h >= 19 && h <= 22) return "Night";
  return "Late Night";
}

function tierClass(tier) {
  return (tier || "").toLowerCase();
}

/* Localized display strings for the canonical English tier/period keys. */
function tierLabel(tier) {
  return I18N.t("tier." + tier);
}
function periodLabel(period) {
  return I18N.t("period." + period);
}

/* ------------------------------------------------------------------ */
/* Nav                                                                */
/* ------------------------------------------------------------------ */
function switchView(name) {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${name}`);
  });
  if (name === "map") setTimeout(() => RiskMap.invalidateSize(), 60);
  if (name === "zones") Zones.load(State.hour);
  if (name === "routing") {
    Routing.init();
    setTimeout(() => Routing.invalidateSize(), 60);
  }
  if (name === "overview") Overview.load();
}

function wireNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
}

/* ------------------------------------------------------------------ */
/* Live map + slider + toggle                                         */
/* ------------------------------------------------------------------ */
function updateSliderUi() {
  document.getElementById("hour-label").textContent = formatHour(State.hour);
  const period = timePeriod(State.hour);
  document.getElementById("period-label").textContent = periodLabel(period);
  document.getElementById("now-pill").style.display =
    State.hour === new Date().getHours() ? "inline-block" : "none";
  document.querySelectorAll("#period-bands .band").forEach((b) => {
    b.classList.toggle("active", b.dataset.period === period);
  });
  document.getElementById("map-badge-text").textContent =
    `${formatHour(State.hour)} · ${periodLabel(period)}`;
}

async function refreshMap() {
  const seq = ++mapReqSeq;
  let summary;

  if (State.level === "road") {
    summary = await RiskMap.renderRoadsGeo(State.hour, State.metric);
    if (seq !== mapReqSeq) return;
    document.getElementById("map-hint-text").textContent = I18N.t("map.primaryRoads");
    document.getElementById("stat-label-total").textContent = I18N.t("stat.roads");
  } else {
    const data = await API.riskMap(State.hour, State.metric, "state");
    if (seq !== mapReqSeq) return;
    await RiskMap.renderStates(data.states, State.metric, State.hour);
    summary = data.summary;
    document.getElementById("map-hint-text").textContent = I18N.t("map.zoomCounties");
    document.getElementById("stat-label-total").textContent = I18N.t("stat.states");
  }

  document.getElementById("stat-total").textContent = summary.total.toLocaleString();
  document.getElementById("stat-high-risk").textContent = summary.high_risk.toLocaleString();
  document.getElementById("stat-alerts").textContent = summary.alerts.toLocaleString();
  document.getElementById("stat-top-zone").textContent = summary.top_zone;
}

let alertReqSeq = 0;
async function refreshSidebarAlerts() {
  const seq = ++alertReqSeq;
  const rows = await API.zones(State.hour, "all");
  if (seq !== alertReqSeq) return;
  const box = document.getElementById("sidebar-alerts");
  const top = rows.filter((r) => r.tier === "Critical" || r.tier === "High").slice(0, 5);
  box.innerHTML = (top.length ? top : rows.slice(0, 5)).map((r) => `
    <div class="alert-row">
      <div class="dot ${tierClass(r.tier)}"></div>
      <div>
        <strong>${r.name}</strong>
        <small>${tierLabel(r.tier)} · ${fmt.prob(r.prob)} · ${periodLabel(timePeriod(State.hour))}</small>
      </div>
    </div>
  `).join("");
}

function wireControls() {
  const slider = document.getElementById("hour-slider");
  slider.value = State.hour;
  updateSliderUi();

  let debounce;
  slider.addEventListener("input", () => {
    State.hour = parseInt(slider.value, 10);
    updateSliderUi();
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      refreshMap();
      refreshSidebarAlerts();
    }, 120);
  });

  document.querySelectorAll("#metric-toggle button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#metric-toggle button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      State.metric = btn.dataset.metric;
      refreshMap();
    });
  });

  document.querySelectorAll("#level-toggle button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#level-toggle button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      State.level = btn.dataset.level;
      refreshMap();
    });
  });

  const search = document.getElementById("map-search-input");
  search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") RiskMap.flyToState(search.value.trim());
  });
  // Suggestions: pick a state to fly to it, or a county/city to zoom into
  // county detail there.
  Autocomplete.attach(search, {
    onSelect: (it) => {
      if (it.type === "state") RiskMap.flyToState(it.label);
      else RiskMap.flyTo(it.lat, it.lng, 8);
    },
  });
}

/* ------------------------------------------------------------------ */
/* Sidebar conditions + footer                                        */
/* ------------------------------------------------------------------ */
async function loadMeta() {
  const meta = await API.meta();
  const now = new Date();
  document.getElementById("cond-time").textContent = formatHour(now.getHours());
  document.getElementById("cond-date").textContent = now.toLocaleDateString(undefined, {
    weekday: "long", month: "short", day: "numeric",
  });
  // Placeholder until live weather resolves (or if location is denied).
  document.getElementById("cond-weather-text").textContent = meta.weather.text;
  document.getElementById("footer-model").textContent = meta.model_name;
  document.getElementById("footer-coverage").textContent = meta.coverage;
}

/* Ask the browser for the user's location, then fetch live weather for it and
   update the Current Conditions widget. Fails quietly if denied/unavailable. */
function loadLiveLocationWeather() {
  const locEl = document.getElementById("cond-location-text");
  if (!("geolocation" in navigator)) {
    locEl.textContent = "Location unavailable";
    return;
  }
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;
      locEl.textContent = `${lat.toFixed(2)}, ${lng.toFixed(2)}`;
      try {
        const w = await API.weather(lat, lng);
        document.getElementById("cond-weather-text").textContent =
          w.ok ? `${w.text} (live)` : w.text;
      } catch (e) {
        /* keep placeholder weather */
      }
    },
    () => { locEl.textContent = "Location off"; },
    { timeout: 8000, maximumAge: 600000 }
  );
}

/* ------------------------------------------------------------------ */
/* Boot                                                               */
/* ------------------------------------------------------------------ */
document.addEventListener("DOMContentLoaded", async () => {
  I18N.wire();
  Theme.wire();
  wireNav();
  RiskMap.init();
  wireControls();
  Zones.wire(() => State.hour);
  Forecast.wire();
  Routing.wire();
  Overview.wire();
  NewsTicker.init();

  // Re-render JS-injected strings (map badges/stats, sidebar alerts) when the
  // language changes. The static labels are handled by I18N.apply() directly.
  document.addEventListener("langchange", () => {
    updateSliderUi();
    refreshMap();
    refreshSidebarAlerts();
  });

  try {
    await Promise.all([
      loadMeta(),
      refreshMap(),
      refreshSidebarAlerts(),
      Forecast.load("Los Angeles, CA"),
    ]);
    loadLiveLocationWeather();
  } catch (err) {
    console.error("Failed to initialize dashboard:", err);
  }
});
