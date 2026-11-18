"""Per-appliance anomaly model: Isolation Forest + learned envelope.  OWNER: Part 2

Why both:
  Isolation Forest only splits inside the range of its training data, so it can't
  extrapolate. A reading ABOVE everything seen in training (an AC at 2400 W when
  its normal maximum is 1900 W) lands in the same leaf as the highest normal
  readings and gets a normal-looking score. So during training we also learn the
  envelope of normal behaviour: the highest power, longest ON period, etc. ever
  seen in a normal week, and the shortest rest between ON periods. A reading
  outside that envelope (plus a MARGIN) is anomalous.
  The forest still covers unusual combinations inside the normal range.
"""
import numpy as np
from sklearn.ensemble import IsolationForest

from anomaly.features import FEATURES

# features where a value ABOVE the normal maximum is anomalous
HIGH = ["power_w", "roll_mean", "on_minutes", "on_frac_30m"]
# features where a value BELOW the normal minimum is anomalous
LOW = ["off_before_min"]
MARGIN = 0.10          # 10 % outside the normal envelope


class ApplianceModel:
    def __init__(self, contamination=0.001, margin=MARGIN, n_estimators=200):
        self.forest = IsolationForest(n_estimators=n_estimators,
                                      contamination=contamination, random_state=42)
        self.margin = margin
        self.hi_idx = [FEATURES.index(f) for f in HIGH]
        self.lo_idx = [FEATURES.index(f) for f in LOW]

    def fit(self, X):
        X = np.asarray(X, dtype=float)
        self.forest.fit(X)
        self.hi = X[:, self.hi_idx].max(axis=0) * (1 + self.margin)
        self.lo = X[:, self.lo_idx].min(axis=0) * (1 - self.margin)
        return self

    def reasons(self, X):
        """Boolean matrix: [forest, each HIGH feature, each LOW feature] per reading."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        forest = (self.forest.predict(X) == -1)[:, None]
        high = X[:, self.hi_idx] > self.hi
        low = X[:, self.lo_idx] < self.lo
        return np.hstack([forest, high, low])

    def predict(self, X):
        """True where a reading is anomalous."""
        return self.reasons(X).any(axis=1)

    def explain(self, x):
        """Short human-readable reason for one anomalous reading."""
        r = self.reasons([x])[0]
        names = ["unusual pattern"] + [f"{f} above normal" for f in HIGH] \
            + [f"{f} below normal" for f in LOW]
        return ", ".join(n for n, hit in zip(names, r) if hit) or "normal"
