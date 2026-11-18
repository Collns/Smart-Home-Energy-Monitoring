"""Live anomaly detection with the trained models.  OWNER: Part 2"""
import os
from datetime import timedelta

import joblib

from alerts import make_alert
from anomaly.features import FeatureState

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
CONSECUTIVE = 12   # need 12 anomalous readings in a row (1 min) -> fewer false alarms
# After an alert, the same appliance must look normal for this long before a NEW alert.
# Stops one incident alerting twice: e.g. when a stuck fridge finally switches off, its
# normal cycle restarts with a shorter rest than usual, which also looks anomalous.
HOLD_OFF = timedelta(minutes=30)


def load_models(model_dir=MODEL_DIR):
    """{appliance: model} for every <appliance>.joblib in model_dir."""
    models = {}
    if os.path.isdir(model_dir):
        for f in os.listdir(model_dir):
            if f.endswith(".joblib"):
                models[f[:-7]] = joblib.load(os.path.join(model_dir, f))
    return models


class AnomalyDetector:
    def __init__(self, model_dir=MODEL_DIR):
        self.models = load_models(model_dir)
        print(f"anomaly models loaded: {sorted(self.models) or 'none (ML alerts off)'}")
        self.state = FeatureState()
        self.streak = {}
        self.episode_end = {}    # appliance -> ts of the last reading in an alert episode

    def check(self, r):
        x = self.state.features(r)            # always update state, even without a model
        model = self.models.get(r["appliance"])
        if model is None:
            return None
        a = r["appliance"]
        if not model.predict([x])[0]:
            self.streak[a] = 0
            return None
        self.streak[a] = self.streak.get(a, 0) + 1
        if self.streak[a] < CONSECUTIVE:
            return None
        last_end = self.episode_end.get(a)
        self.episode_end[a] = r["ts"]
        if self.streak[a] == CONSECUTIVE and (last_end is None or r["ts"] - last_end > HOLD_OFF):
            return make_alert(r, "anomaly", "warning",
                              f"unusual power pattern on {a}: {model.explain(x)}")
        return None
