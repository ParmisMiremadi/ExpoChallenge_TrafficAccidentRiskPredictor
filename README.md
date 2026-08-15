# SafeVector — Traffic Accident Risk Predictor

Predicting **where and when** traffic accidents are likely to occur — *before* they
happen — so that road users, planners, and responders can act early.

SafeVector is a machine-learning system that scores every US county and every
primary-road segment for accident **occurrence risk** under live conditions
(time of day, season, weather, road infrastructure), and presents the result as
an interactive early-warning dashboard.

---

## Quick start

**Windows:** double-click **`run.bat`**. **Any platform:**

```bash
pip install -r requirements.txt      # first time only
python run.py                        # then open http://127.0.0.1:5000
```

Runs with **no API keys**. The first launch takes ~15–20 seconds to fetch the
live weather grid, then it's instant. Full details in §10.

**Dependencies** (installed by the command above, from `requirements.txt`):
Flask, Flask-CORS, XGBoost, scikit-learn, pandas, and NumPy — Python 3.12.
The frontend needs no install step; it loads Leaflet, Chart.js, and Plotly.js
from a CDN at runtime.

---

## 1. The problem, framed correctly

The goal is **occurrence risk** — the probability that an accident happens in a
given place and time window — not "how severe would a crash be if one occurred."
That distinction drives the whole design:

- **Target:** `P(≥1 accident | road × date × time-period)`, a binary
  occurrence label.
- **Learning from absence too:** the model is trained on real accidents *and* on
  matched **no-accident** road-time cells, sampled to preserve real exposure. A
  model trained only on crashes learns severity, not *where crashes happen*.

This is what lets the map answer "which areas are dangerous right now," rather
than "which past crashes were bad."

---

## 2. How it addresses the competition brief

| Brief item | How SafeVector delivers it |
|---|---|
| Analyze road & traffic data | 3.8M road-time records; 22 features spanning geography, road infrastructure, time, and weather (§5) |
| Predict accident risk levels | Calibrated probability + Low/Medium/High/Critical tier for any place & time (§6) |
| Detect dangerous zones | Live ranked list of highest-risk counties, each with its contributing factors |
| Adapt predictions to seasonal conditions | `Season` and cyclical `Month` are model inputs — the same road scores differently across the year, automatically |
| Reduce false alarms | Prior-correction calibration + a tuned operating point balancing recall vs. precision (§7) |
| Risk-level predictions | Interactive map (state choropleth + road network) reacting to an hour slider |
| High-risk area identification | Map hotspots + the Dangerous Zones panel |
| Safety alerts & reports | Live alerts feed; exportable CSV report of top zones |
| Prevention recommendations | Each zone carries a plain-language recommendation derived from its dominant risk factor |
| **Reliable early warning; balance sensitivity vs. false alarms** | 7-day / 24-hour **Risk Forecast**, and an operating point of **recall 0.95 at precision 0.73** (§7) |

---

## 3. The dashboard

Everything runs from a single backend. Five sections:

1. **Live Risk Map** — the whole US, scored live. Toggle **State ↔ Road**
   and **Risk ↔ Severity**. In State mode, zooming in past state level swaps
   the choropleth to a **per-county view** (each of ~2,850 modeled counties
   scored individually; counties outside the model's coverage are filled by
   interpolating their nearest scored neighbors, clearly marked as estimated).
   Road mode renders the real 17,424-segment primary-road network. An **hour
   slider** (default = now) re-scores the country; season, weekend, and
   weather are inferred from the current date and a live forecast. Click any
   area for its probability, tier, and reasons.
2. **Dangerous Zones & Alerts** — the highest-risk counties under current
   conditions, each with its risk %, contributing factors, a prevention
   recommendation, and expandable details. One-click CSV export.
3. **Risk Forecast** — search any US city → its risk over the **next 24 hours**
   and **next 7 days**, with peak/safe windows (uses the real weather forecast).
4. **Safe Routing** — enter start & destination; candidate routes are ranked by
   the model's per-segment risk, surfacing the *safest* route, not just the
   fastest.
5. **Project Overview** — model performance at a glance: Plotly speedometer
   gauges for ROC-AUC, PR-AUC, precision/recall/F1, Brier score, county-risk
   Spearman correlation, and hotspot precision/recall, plus feature-importance
   and calibration charts, served from `/api/metrics`.

Every location search (Live Risk Map, Risk Forecast, Safe Routing's From/To)
shares one **autocomplete** backed by `/api/suggest`, ranking states, counties,
and cities as you type.

The whole app supports **dark mode** (persisted toggle) and **English, فارسی,
हिन्दी, and Español** (persisted, with full RTL layout for Farsi) — both the
static UI and the strings each view injects at runtime are translated. A brief
**welcome screen** greets first paint and is dismissed with any key press or
click.

A **live news ticker** (bottom) blends real National Weather Service alerts with
optional AI-summarized traffic-news headlines.

---

## 4. What's beyond the brief (the innovations)

Section 2 covers what the brief asked for. This is what we added on top of it:

- **County-level drill-down** — zooming into the Live Risk Map's State view
  swaps the choropleth to ~2,850 individually-scored counties. Counties
  outside the model's direct coverage are filled by interpolating their
  nearest scored neighbors instead of leaving a gap, and are clearly marked
  as estimated.
- **Risk vs. severity** — state/county risk is a *live average*
  of the model's per-point predictions; road risk is **not** an average, each
  of the 17,424 segments gets its own independent live prediction; severity
  (either view) is a real historical aggregate, never a model output. The map
  never conflates "how likely" with "how bad."
- **One shared autocomplete** — a single ranked state/county/city search
  (`/api/suggest`) powers the map search, the forecast search, and both Safe
  Routing fields.
- **Model transparency, built in** — the Project Overview tab renders the
  real evaluation metrics (ROC-AUC, PR-AUC, precision/recall/F1, Brier,
  county-rank Spearman, hotspot precision/recall) as live speedometer gauges,
  so judges see the numbers, not just a claim in a README.
- **Full i18n, not just labels** — English, Farsi, Hindi, and Spanish,
  including a complete RTL layout for Farsi; both the static UI and the
  strings each view injects at runtime (tiers, alerts, popups) are translated.
- **Theme-aware** — dark mode swaps the UI *and* the map's
  basemap tiles (CARTO Voyager ↔ Dark Matter), not just colors.
- **Zero setup friction** — the entire core experience (map, zones, forecast,
  routing, news) runs with no API keys at all; AI-summarized news is the only
  optional add-on.
- **A real welcome screen** — a typewriter-style intro with a live feature
  showcase, dismissed with any key press or click, transitioning into the app
  through the logo.

---

## 5. The model

- **Algorithm:** gradient-boosted trees (`XGBoost` classifier), with a logistic
  regression baseline for comparison.
- **Features (22):**
  - *Geography* — latitude, longitude
  - *Time* — cyclical hour (`Hour_sin/cos`), cyclical month (`Month_sin/cos`),
    `Season`, `Time_Period`, `Is_Weekend`, `DayOfWeek`
  - *Road infrastructure* — `Junction`, `Crossing`, `Traffic_Signal`, `Stop`,
    `Station`, `Amenity`
  - *Weather* — temperature, precipitation, wind, humidity, snow depth, and an
    adverse-conditions flag
- **Top drivers** (by gain): `Stop`, `Hour_cos`, `Is_Weekend`, `Traffic_Signal`,
  `Time_Period`, `Month_cos`, `Junction`, `Crossing` — a mix of *where* (road
  layout) and *when* (commute rhythm), exactly as expected.
- **Data:** the [US Accidents](https://smoosavi.org/datasets/us_accidents)
  dataset (2021–2023 window, ~3.8M modeling rows after building no-accident
  cells), joined to historical weather from the free
  [Open-Meteo ERA5 archive](https://open-meteo.com/), plus US Census
  [TIGER/Line](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html)
  primary roads.
- **Honest evaluation split:** train on **2021**, test on **2022** (both full
  years, no leakage across time). The deployed model is then refit on all
  available data for serving.

---

## 6. Making the numbers trustworthy (calibration)

The training set is balanced ~50/50 so the model can learn, but the real-world
base rate of an accident in any single road-time cell is tiny
(**π_true ≈ 0.114%**). Raw classifier scores are therefore inflated — a naïve
"92% risk" would be nonsense.

We apply **prior-correction**: a single log-odds shift that rescales every score
from the balanced prior to the true base rate. This preserves the ranking
(so the map's *relative* danger is unchanged) while producing **plausible
absolute probabilities** — e.g. a busy interstate at rush hour reads a few
percent, a quiet rural road a fraction of a percent. Risk tiers (Low → Critical)
come from fixed quantile cutoffs of these calibrated probabilities.

---

## 7. Results

Metrics are from the honest **2021 → 2022** temporal split (1.82M train / 1.69M
test rows).

**Discrimination**

| Metric | XGBoost | Logistic baseline |
|---|---|---|
| ROC-AUC | **0.769** | 0.670 |
| PR-AUC | **0.863** | 0.782 |

**Does it find the right places?** (2022 held-out)

| Spatial check | Result |
|---|---|
| County risk rank correlation (Spearman) | **0.987** |
| Top-20 dangerous counties overlap with actual | **19 / 20** |
| Hotspot precision (top-quintile counties) | **1.00** |
| Hotspot recall | **0.914** |

**Sensitivity vs. false alarms** — the core competition criterion. At the chosen
operating point (threshold 0.4):

- **Recall 0.95** — catches 95% of true accident cells (few missed warnings)
- **Precision 0.73** — most alerts are real (false alarms controlled)
- **F1 0.82**

Optimizing for **PR-AUC** (not raw accuracy) and pairing it with calibration is
precisely what keeps early warnings *reliable* rather than noisy.

---

## 8. Live data integrations (all keyless except the optional news layer)

- **Weather** — [Open-Meteo](https://open-meteo.com/) forecast on a cached
  national grid drives the live map, the forecast view, and the current-conditions
  widget (with browser geolocation).
- **Routing** — the public [OSRM](http://project-osrm.org/) engine provides
  candidate routes, which we re-rank by model risk.
- **News ticker** — live [National Weather Service alerts](https://www.weather.gov/documentation/services-web-api)
  (free, no key); optionally enriched with traffic-news summaries via Jina AI +
  Google Gemini if keys are supplied.

---

## 9. Architecture

```
├── backend/
│   ├── app.py                 Flask app: serves the UI + JSON API
│   ├── model_service.py       load model, predict → calibrate → tier
│   ├── serving.py             score state map / roads / zones / forecast
│   ├── weather_service.py     cached Open-Meteo weather grid
│   ├── routing_service.py     OSRM routes ranked by model risk
│   ├── news_service.py        NWS + optional Jina/Gemini ticker feed
│   ├── artifacts/             trained model + serving tables + metrics
│   └── pipeline/              data-prep & training scripts
└── frontend/
    ├── html/index.html        app shell (sidebar + 5 views)
    ├── css/style.css          theme tokens, light/dark, RTL
    ├── js/                    vanilla JS, one module per view/concern
    ├── img/brand/             logo + favicon assets
    └── data/                  states/counties/roads GeoJSON
```

The serving layer was validated to **reproduce the trained model's metrics
exactly** (it re-derives the calibration cutoffs to 6 decimals), and the
50-points-per-county serving sample reproduces full-data county risk at
Spearman **0.998** — so the app is fast without sacrificing fidelity.

---

## 10. Running it

**Windows — double-click** `run.bat`, then open
<http://127.0.0.1:5000>.

**Any platform — one command:**

```bash
pip install -r requirements.txt   # first time only
python run.py                     # then open http://127.0.0.1:5000
```

`run.py` simply launches `backend/app.py` (which is where the model, its
modules, and the frontend live). First launch takes ~15–20 seconds to fetch the
live weather grid; after that it is cached.

The app works fully with **no API keys** — weather, routing, and NWS alerts are
all keyless. To enable the optional AI traffic-news layer, copy `.env.example`
to `.env` and add your Jina and Gemini keys.

**Rebuilding from scratch** (needs the raw dataset): the `pipeline/` scripts run
in order — `clean_dataset_v2.py` → `fetch_weather.py` → `join_features.py` →
`train_model.py` → `build_serving_table.py` → `build_road_features.py`.

---

## 11. Honest limitations & future work

- **Road-view infrastructure** is inferred from each road's containing county
  (the TIGER shapefile carries no signal/stop data); the coordinates and route
  class are real. Interstates are treated as limited-access (junctions only).
- **Forecast search is county-level** (the model has no street index), so a bare
  city resolves to its dominant county.
- **No free nationwide live-traffic feed** exists; traffic *exposure* is captured
  implicitly through geography and road infrastructure. A live AADT/TomTom
  overlay is a natural extension.
- **Routing** uses the public OSRM demo server; a self-hosted engine would be
  more robust for production.

---

## 12. Credits

- Accident data: *US Accidents* (Moosavi et al.).
- Weather: Open-Meteo (ERA5 archive + forecast). Roads & state boundaries: US
  Census TIGER/Line. County boundaries:
  [plotly/datasets](https://github.com/plotly/datasets) `geojson-counties-fips`
  (US Census derived). Routing: OSRM / OpenStreetMap. Map tiles: CARTO
  (Voyager / Dark Matter) on OpenStreetMap data. Alerts: US National Weather
  Service.
- Built for INNOVERSE 2026.

---

## 13. Team

- َAmirhossein Jafarnezhad (Team Leader): aiamirjd@gmail.com
- Parmis Miremadizayd: parmis.mi83@gmail.com
- Amirreza Abdi Aladezgeh: Amirreza.abdi2005@gmail.com
- Mostafa Akbari: mooak13860425@gmail.com
- AmirAli Ansari kalodani: 
