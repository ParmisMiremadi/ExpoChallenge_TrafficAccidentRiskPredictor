# RoadGuard AI — Web Dashboard

Serving layer for the model trained in `Traffic_Accident_Risk_Predictor_v2.ipynb`.
Same pipeline, same numbers — this is just a UI + API on top of it.

## Structure

```
webapp/
├── backend/
│   ├── app.py              Flask API + serves the static frontend
│   ├── model_service.py    Exact port of the notebook's prediction/scenario logic
│   ├── artifacts/          Copied from the notebook's joblib.dump() output
│   ├── data/                Precomputed JSON (dangerous zones, alerts, ...)
│   ├── requirements.txt
│   └── venv/                Isolated virtualenv (kept separate from the
│                             Anaconda base env, which has a broken Flask/Jinja2)
└── frontend/
    ├── html/index.html
    ├── css/style.css
    └── js/ (api.js, map.js, charts.js, predictor.js, main.js)
```

## Run it

```bash
cd webapp/backend
venv\Scripts\python.exe app.py
```

Then open **http://127.0.0.1:5000**.

## Regenerating data after re-running the notebook

If the notebook is re-run and produces new artifacts (`final_model.pkl`, etc.),
copy them into `backend/artifacts/`, then regenerate the precomputed JSON:

```bash
cd webapp/backend
venv\Scripts\python.exe export_data.py
```

(`export_data.py` reads `Dataset/cleaned_us_accidents.csv` directly — same
Source1/2021-2023 filtering as the notebook — and rescoring the 2023 test
slice with whatever model is in `artifacts/final_model.pkl`.) Restart `app.py`
afterwards; it loads the JSON files once at startup.

## What's live vs. precomputed

- **Live, on demand:** `/api/predict` and `/api/scenario-simulator` run the
  actual model for whatever inputs the user picks in the Risk Predictor tab.
- **Precomputed once from the 2023 test set:** dangerous zones, state
  summary, seasonal/time-of-day risk, and the alerts/reports list. These are
  evaluation results, not something a form input changes, so they're
  generated once by `export_data.py` and served straight from memory.
