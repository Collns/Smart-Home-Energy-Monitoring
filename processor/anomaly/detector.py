"""Live anomaly detection with the trained models.  OWNER: Part 2"""
import os

import joblib

from alerts import make_alert
from anomaly.features import FeatureState

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
CONSECUTIVE = 6    # need 6 anomalous readings in a row (30 s) -> fewer false alarms


class AnomalyDetector:
    def __init__(self):
        self.models = {}
        if os.path.isdir(MODEL_DIR):
            for f in os.listdir(MODEL_DIR):
                if f.endswith(".joblib"):
                    self.models[f[:-7]] = joblib.load(os.path.join(MODEL_DIR, f))
        print(f"anomaly models loaded: {sorted(self.models) or 'none (ML alerts off)'}")
        self.state = FeatureState()
        self.streak = {}

    def check(self, r):
        model = self.models.get(r["appliance"])
        x = self.state.features(r)
        if model is None:
            return None
        a = r["appliance"]
        if model.predict([x])[0] == -1:
            self.streak[a] = self.streak.get(a, 0) + 1
            if self.streak[a] == CONSECUTIVE:
                return make_alert(r, "anomaly", "warning", f"unusual power pattern on {a}")
        else:
            self.streak[a] = 0
        return None
