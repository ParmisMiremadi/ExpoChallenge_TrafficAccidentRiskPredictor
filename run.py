"""SafeVector — convenience launcher.

Start the whole app from the project root, no matter where you run it from:

    python webapp_v3/run.py

This just launches backend/app.py in its own directory (where its modules,
model artifacts, and the frontend live), so nothing needs to be moved.
"""
import os
import subprocess
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")

banner = (
    "=" * 60
    + "\n  SafeVector — Traffic Accident Risk Predictor"
    + "\n  Open  ->  http://127.0.0.1:5000"
    + "\n  (first launch fetches live weather; allow ~15-20 seconds)"
    + "\n  Press Ctrl+C to stop.\n"
    + "=" * 60
)
print(banner, flush=True)

try:
    subprocess.run([sys.executable, "app.py"], cwd=BACKEND)
except KeyboardInterrupt:
    print("\nSafeVector stopped.")
