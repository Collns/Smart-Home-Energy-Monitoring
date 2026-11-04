"""Train one Isolation Forest per appliance.  OWNER: Part 2

Usage (inside the processor container or a venv):
    python -m anomaly.train /data/buffer_PowerRaw.jsonl
Or export a week of PowerRaw from ADX to JSONL/CSV and point at that file.

Tip: run the simulator with SPEED=120 and FAULT_RATE=0 to generate a clean
"first week" of data in ~1.5 hours.
"""
import os
import sys

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

from anomaly.features import features_from_frame

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")


def main(path):
    df = pd.read_json(path, lines=True) if path.endswith(".jsonl") else pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["ts"])
    for appliance, g in df.sort_values("ts").groupby("appliance"):
        X = features_from_frame(g)
        model = IsolationForest(n_estimators=200, contamination=0.01, random_state=42)
        model.fit(X)
        joblib.dump(model, os.path.join(MODEL_DIR, f"{appliance}.joblib"))
        print(f"trained {appliance}: {len(X)} samples")


if __name__ == "__main__":
    main(sys.argv[1])
