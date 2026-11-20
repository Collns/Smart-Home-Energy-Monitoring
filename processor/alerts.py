"""Threshold alerts.  OWNER: Part 2

ThresholdTracker.check(reading) -> alert dict | None
An alert fires when an appliance stays above its limit for `duration`.
"""
from datetime import datetime, timedelta, timezone

# appliance: list of (watts limit, sustained duration). Each rule alerts on its own.
# Limits sit above the simulator's normal behaviour (simulator/profiles.py), so only
# faults or misuse trip them. Injected faults last 5-30 min (simulator.py), so the
# durations are short enough for the alert-timing test to see them.
THRESHOLDS = {
    # normal peak ~2000 W around 15:00 for a few readings; "overload" fault = 2400 W
    "air_conditioner": [(2000, timedelta(minutes=30))],
    # normal compressor cycle is 15 min on / 25 min off; "stuck on" = nonstop
    "refrigerator": [(100, timedelta(minutes=20))],
    # short 1100 W bursts at meal times; 10 min nonstop = left running / fault
    "microwave": [(900, timedelta(minutes=10))],
    # cycle: 100 W fill, 500 W wash, 800 W spin, 50 min total
    "washing_machine": [(1000, timedelta(minutes=5)),     # drawing too much
                        (50, timedelta(hours=2))],        # cycle stuck / never ends
    # 4500 W bursts, never sustained in normal use
    "water_heater": [(4000, timedelta(hours=1))],
    # 120 W from 18:00 to midnight (6 h)
    "television": [(250, timedelta(minutes=5)),           # spike / fault
                   (50, timedelta(hours=8))],             # left on
}


def _fmt(d):
    mins = int(d.total_seconds() // 60)
    return f"{mins // 60} h" if mins >= 60 and mins % 60 == 0 else f"{mins} min"


class ThresholdTracker:
    def __init__(self):
        self.above_since = {}      # (appliance, limit) -> datetime it went above limit
        self.fired = set()         # (appliance, limit) rules with an active alert

    def check(self, r):
        """Returns the first alert that fires for this reading, or None."""
        a = r["appliance"]
        alert = None
        for limit, duration in THRESHOLDS.get(a, []):
            key = (a, limit)
            if r["power_w"] <= limit:
                self.above_since.pop(key, None)
                self.fired.discard(key)
                continue
            start = self.above_since.setdefault(key, r["ts"])
            # one alert per reading; if two rules trip at once, the second fires next reading
            if r["ts"] - start >= duration and key not in self.fired and alert is None:
                self.fired.add(key)
                alert = make_alert(r, "threshold", "warning",
                                   f"{a} above {limit} W for {_fmt(duration)}")
        return alert


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

    def check(self, topic, payload, now=None, retained=False):
        """retained=True: an old status the broker kept from before we connected
        (MQTT retain flag). We note it but don't alert, otherwise a processor
        restart re-announces every past offline as if it just happened."""
        parts = topic.split("/")
        if len(parts) != 4:
            return None
        appliance = parts[2]
        status = payload.strip().lower()
        if status not in ("online", "offline"):
            return None
        prev = self.last.get(appliance)
        self.last[appliance] = status
        if retained:
            return None
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
