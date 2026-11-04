"""Feature engineering shared by training and live detection.  OWNER: Part 2"""
from collections import deque

WINDOW = 12   # last 12 readings = 1 minute at 5 s


class FeatureState:
    """Keeps a short rolling window per appliance for live feature building."""

    def __init__(self):
        self.windows = {}

    def features(self, r):
        w = self.windows.setdefault(r["appliance"], deque(maxlen=WINDOW))
        w.append(r["power_w"])
        mean = sum(w) / len(w)
        return [r["power_w"], mean, max(w) - min(w), r["ts"].hour]


def features_from_frame(df):
    """Same features computed on a pandas DataFrame of one appliance (sorted by ts)."""
    out = df[["power_w"]].copy()
    out["roll_mean"] = df["power_w"].rolling(WINDOW, min_periods=1).mean()
    roll = df["power_w"].rolling(WINDOW, min_periods=1)
    out["roll_range"] = roll.max() - roll.min()
    out["hour"] = df["ts"].dt.hour
    return out.values
