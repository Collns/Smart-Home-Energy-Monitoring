import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from anomaly import detector as det
from anomaly.features import FEATURES, OFF_CAP, FeatureState, features_from_frame
from anomaly.model import ApplianceModel

T0 = datetime(2026, 11, 2, tzinfo=timezone.utc)


def frame(watts, appliance="refrigerator"):
    return pd.DataFrame({"appliance": appliance, "power_w": watts,
                         "ts": [T0 + timedelta(seconds=5 * i) for i in range(len(watts))]})


def live(df):
    st = FeatureState()
    return np.array([st.features(r) for r in df.to_dict("records")])


# ---- features: live and training must agree exactly ----
@pytest.mark.parametrize("start_on", [True, False])
def test_live_features_match_training_features(start_on):
    random.seed(0)
    watts, on = [], start_on
    for _ in range(40):                                   # random ON/OFF runs with noise
        n = random.randint(1, 400)
        watts += [random.gauss(150 if on else 3, 2) for _ in range(n)]
        on = not on
    df = frame(watts)
    assert features_from_frame(df).shape[1] == len(FEATURES)
    np.testing.assert_allclose(live(df), features_from_frame(df))


def test_on_minutes_and_off_before():
    # unknown first OFF period, ON 10 min, OFF 5 min, ON again
    df = frame([3] * 60 + [150] * 120 + [3] * 60 + [150] * 12)
    X = features_from_frame(df)
    i_on, i_off_before, i_on_min = 181 + 60, FEATURES.index("off_before_min"), FEATURES.index("on_minutes")
    assert X[60, i_off_before] == OFF_CAP                 # previous OFF started before the data
    assert X[179, i_on_min] == pytest.approx(10)
    assert X[i_on - 1, i_off_before] == pytest.approx(5)  # rested only 5 min


# ---- model: Isolation Forest + envelope ----
def normal_week_like(n=5000):
    rng = np.random.default_rng(0)
    return np.column_stack([rng.normal(1500, 30, n), rng.normal(1500, 10, n), rng.uniform(0, 60, n),
                            rng.integers(0, 24, n), rng.uniform(0, 20, n), rng.uniform(0, .6, n),
                            rng.uniform(25, 120, n)])


def test_envelope_catches_values_beyond_training_range():
    X = normal_week_like()
    m = ApplianceModel(contamination=0.0001).fit(X)
    high = X[0].copy()
    high[0] = high[1] = 2400                              # far above normal max (~1600)
    early = X[0].copy()
    early[FEATURES.index("off_before_min")] = 5           # restarted after only 5 min
    assert m.predict([high, early]).all()
    assert "power_w above normal" in m.explain(high)
    assert "off_before_min below normal" in m.explain(early)
    assert m.predict(X).mean() < 0.01                     # training data mostly normal


# ---- detector: consecutive rule and hold-off ----
class FlagAbove:
    """Fake model: anomalous above 1000 W; below 3000 W it shows no sign of a new fault."""
    def predict(self, X):
        return np.array([x[0] > 1000 for x in X])

    def settling_only(self, X):
        return np.array([x[0] < 3000 for x in X])

    def explain(self, x):
        return "test"


def run_detector(watts):
    d = det.AnomalyDetector.__new__(det.AnomalyDetector)
    d.models, d.state = {"microwave": FlagAbove()}, FeatureState()
    d.streak, d.alerted, d.episode_end = {}, {}, {}
    alerts = []
    for i, w in enumerate(watts):
        a = d.check({"appliance": "microwave", "ts": T0 + timedelta(seconds=5 * i), "power_w": w})
        if a:
            alerts.append(i)
    return alerts


def test_alert_after_consecutive_readings_only():
    k = det.CONSECUTIVE
    assert run_detector([2000] * (k - 1) + [2] + [2000] * (k - 1)) == []
    assert run_detector([2] * 5 + [2000] * (k + 20)) == [5 + k - 1]


def test_hold_off_only_silences_settling_after_an_incident():
    k = det.CONSECUTIVE
    short = int(det.HOLD_OFF / timedelta(seconds=5)) // 2
    long = int(det.HOLD_OFF / timedelta(seconds=5)) + 10
    assert len(run_detector([2000] * k + [2] * short + [2000] * k)) == 1   # settling: held off
    assert len(run_detector([2000] * k + [2] * short + [3500] * k)) == 2   # clear new fault: alerts
    assert len(run_detector([2000] * k + [2] * long + [2000] * k)) == 2    # after hold-off: alerts


def test_settling_only_means_no_power_or_duration_sign():
    X = normal_week_like()
    m = ApplianceModel(contamination=0.0001).fit(X)
    early = X[0].copy()
    early[FEATURES.index("off_before_min")] = 5            # only "restarted too soon"
    high = early.copy()
    high[0] = high[1] = 2400                               # plus far too much power
    assert m.settling_only([early, high]).tolist() == [True, False]


# ---- end to end on simulator profiles (small, ~10 s) ----
def test_detects_most_injected_faults(tmp_path):
    from anomaly import generate, train
    import eval_anomaly as ev

    random.seed(1)
    start = datetime(2026, 11, 2, 5, tzinfo=timezone.utc)
    generate.generate(3, 0, start, tmp_path / "train.jsonl")
    random.seed(2)
    generate.generate(1, 0.0005, start + timedelta(days=7), tmp_path / "test.jsonl",
                      tmp_path / "faults.csv")
    train.main(str(tmp_path / "train.jsonl"), str(tmp_path / "models"))
    table, _ = ev.evaluate(*ev.load(tmp_path / "test.jsonl", tmp_path / "faults.csv",
                                    model_dir=str(tmp_path / "models")))
    recall = table["detected"].sum() / table["faults"].sum()
    fa_per_hour = table["false_alarms"].sum() / table["hours"].mean()
    assert recall >= 0.85, table
    assert fa_per_hour <= 0.5, table
