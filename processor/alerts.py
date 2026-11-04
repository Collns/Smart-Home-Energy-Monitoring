"""Threshold alerts.  OWNER: Part 2

ThresholdTracker.check(reading) -> alert dict | None
An alert fires when an appliance stays above its limit for `duration`.
"""
from datetime import timedelta

# appliance: (watts limit, sustained duration)
THRESHOLDS = {
    "air_conditioner": (2000, timedelta(minutes=30)),
    "refrigerator": (100, timedelta(hours=2)),      # compressor never stops
    "water_heater": (4000, timedelta(hours=1)),
    # TODO Part 2: tune / add the rest
}


class ThresholdTracker:
    def __init__(self):
        self.above_since = {}      # appliance -> datetime it went above limit
        self.fired = set()         # appliances with an active alert

    def check(self, r):
        rule = THRESHOLDS.get(r["appliance"])
        if not rule:
            return None
        limit, duration = rule
        a = r["appliance"]
        if r["power_w"] <= limit:
            self.above_since.pop(a, None)
            self.fired.discard(a)
            return None
        start = self.above_since.setdefault(a, r["ts"])
        if r["ts"] - start >= duration and a not in self.fired:
            self.fired.add(a)
            return make_alert(r, "threshold", "warning",
                              f"{a} above {limit} W for {int(duration.total_seconds() // 60)} min")
        return None


def make_alert(r, kind, severity, message):
    return {
        "ts": r["ts"].isoformat().replace("+00:00", "Z"),
        "appliance": r["appliance"],
        "type": kind,
        "severity": severity,
        "value": r["power_w"],
        "message": message,
    }
