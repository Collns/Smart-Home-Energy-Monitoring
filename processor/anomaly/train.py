"""Train one anomaly model per appliance (Isolation Forest + envelope).  OWNER: Part 2

Train on NORMAL data only (no injected faults):
    cd processor
    python -m anomaly.train ../data/train.jsonl
The file can be the processor's buffer (data/buffer_PowerRaw.jsonl from a live run with
FAULT_RATE=0), a PowerRaw export from ADX (JSONL/CSV), or anomaly/generate.py output:
    python processor/anomaly/generate.py --days 7 --out data/train.jsonl
"""
import argparse
import os

import joblib
import pandas as pd

from anomaly.features import features_from_frame
from anomaly.model import MARGIN, ApplianceModel

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")


def main(path, model_dir=MODEL_DIR, contamination=0.001, margin=MARGIN):
    df = pd.read_json(path, lines=True) if path.endswith(".jsonl") else pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    if "filled" in df:                       # train on real readings only
        df = df[df["filled"] != True]  # noqa: E712
    os.makedirs(model_dir, exist_ok=True)
    for appliance, g in df.sort_values("ts").groupby("appliance"):
        X = features_from_frame(g)
        model = ApplianceModel(contamination=contamination, margin=margin).fit(X)
        joblib.dump(model, os.path.join(model_dir, f"{appliance}.joblib"))
        print(f"trained {appliance}: {len(X)} samples")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train anomaly models on normal data")
    ap.add_argument("path")
    ap.add_argument("--models", default=MODEL_DIR)
    ap.add_argument("--contamination", type=float, default=0.001)
    ap.add_argument("--margin", type=float, default=MARGIN)
    a = ap.parse_args()
    main(a.path, a.models, a.contamination, a.margin)
