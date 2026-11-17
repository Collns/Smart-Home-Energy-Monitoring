"""Threshold alerts.  OWNER: Part 2

ThresholdTracker.check(reading) -> alert dict | None
An alert fires when an appliance stays above its limit for `duration`.
"""
from datetime import datetime, timedelta, timezone

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


class StatusTracker:
    """Turns home/{room}/{appliance}/status messages into offline alerts.

    The simulator sets a retained Last Will of "offline", so the broker publishes it
    when a plug drops without disconnecting cleanly. We only alert on a change
    (online -> offline), so a repeated or retained "offline" doesn't fire twice.
    """

    def __init__(self):
        self.last = {}             # appliance -> "online" / "offline"

    def check(self, topic, payload, now=None):
        parts = topic.split("/")
        if len(parts) != 4:
            return None
        appliance = parts[2]
        status = payload.strip().lower()
        if status not in ("online", "offline"):
            return None
        prev = self.last.get(appliance)
        self.last[appliance] = status
        if status == "offline" and prev != "offline":
            now = now or datetime.now(timezone.utc)
            return {
                "ts": now.isoformat().replace("+00:00", "Z"),
                "appliance": appliance,
                "type": "offline",
                "severity": "critical",
                "value": 0.0,
                "message": f"{appliance} went offline",
            }
        return None
