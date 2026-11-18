"""Feature engineering shared by training and live detection.  OWNER: Part 2

Features per reading (same order live and in training, see FEATURES):
  power_w          current watts
  roll_mean        average watts over the last minute
  roll_range       max - min watts over the last minute
  hour             hour of day (UTC)
  on_minutes       how long the appliance has been continuously ON (> ON_W)
  on_frac_30m      fraction of the last 30 min it was ON
  off_before_min   while ON: how long it was OFF before switching on (capped at OFF_CAP)

on_minutes / on_frac_30m catch faults that look normal reading by reading but last
too long (fridge compressor stuck on, water heater that never stops).
off_before_min catches switching on too soon (normal fridge rests 25 min, water
heater cools down 25 min between heating cycles).
"""
from collections import deque

import pandas as pd

FEATURES = ["power_w", "roll_mean", "roll_range", "hour",
            "on_minutes", "on_frac_30m", "off_before_min"]
WINDOW = 12        # last 12 readings = 1 minute at 5 s
LONG_WINDOW = 360  # last 360 readings = 30 minutes
ON_W = 50          # above this an appliance counts as ON (standby is 0.5-5 W)
TICK_MIN = 5 / 60  # minutes per reading
OFF_CAP = 120.0    # minutes; also used when the previous OFF period is unknown


class FeatureState:
    """Keeps short rolling windows per appliance for live feature building."""

    def __init__(self):
        self.windows = {}
        self.on_windows = {}
        self.on_run = {}        # readings in the current ON period
        self.off_run = {}       # readings in the current OFF period (None = started before we saw it)
        self.off_before = {}    # minutes OFF before the current ON period

    def features(self, r):
        a = r["appliance"]
        w = self.windows.setdefault(a, deque(maxlen=WINDOW))
        w.append(r["power_w"])
        on = r["power_w"] > ON_W
        ow = self.on_windows.setdefault(a, deque(maxlen=LONG_WINDOW))
        ow.append(on)

        if on:
            if self.on_run.get(a, 0) == 0:                 # just switched on
                off = self.off_run.get(a)
                self.off_before[a] = OFF_CAP if off is None else min(off * TICK_MIN, OFF_CAP)
            self.on_run[a] = self.on_run.get(a, 0) + 1
            self.off_run[a] = 0
            off_before = self.off_before[a]
        else:
            if a not in self.on_run:
                self.off_run[a] = None                     # OFF since before we started
            elif self.off_run.get(a) is not None:
                self.off_run[a] += 1
            self.on_run[a] = 0
            off_before = OFF_CAP

        return [r["power_w"], sum(w) / len(w), max(w) - min(w), r["ts"].hour,
                self.on_run[a] * TICK_MIN, sum(ow) / len(ow), off_before]


def features_from_frame(df):
    """Same features computed on a pandas DataFrame of one appliance (sorted by ts)."""
    p = df["power_w"].reset_index(drop=True)
    roll = p.rolling(WINDOW, min_periods=1)
    on = (p > ON_W).astype(int)
    on_run = on.groupby((on == 0).cumsum()).cumsum()     # consecutive ON readings

    # Length of the OFF period before each ON period. Runs are numbered 1, 2, 3...
    # Run 1 started before the data did, so its length is unknown: only runs >= 3
    # have a fully observed previous run.
    run_id = (on != on.shift()).cumsum()
    run_len = run_id.value_counts().sort_index()
    prev_len = run_len.shift(1).where(run_len.index >= 3)
    off_before = (run_id.map(prev_len) * TICK_MIN).clip(upper=OFF_CAP).fillna(OFF_CAP)
    off_before = off_before.where(on == 1, OFF_CAP)

    out = {
        "power_w": p,
        "roll_mean": roll.mean(),
        "roll_range": roll.max() - roll.min(),
        "hour": df["ts"].dt.hour.reset_index(drop=True),
        "on_minutes": on_run * TICK_MIN,
        "on_frac_30m": on.rolling(LONG_WINDOW, min_periods=1).mean(),
        "off_before_min": off_before,
    }
    return pd.DataFrame(out).values
