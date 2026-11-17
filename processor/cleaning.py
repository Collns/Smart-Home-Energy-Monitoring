"""Validate and clean incoming readings.  OWNER: Part 2

parse_reading(topic, payload) -> dict | None
Returns None for anything that should be dropped.
"""
import json
from datetime import datetime

REQUIRED = ("device_id", "room", "appliance", "ts", "seq", "power_w", "voltage_v", "current_a")

# Max plausible watts per appliance (anything above is dropped as a sensor error)
MAX_WATTS = {
    "refrigerator": 800,
    "microwave": 2000,
    "washing_machine": 2500,
    "water_heater": 6000,
    "air_conditioner": 4000,
    "television": 600,
}


def parse_reading(topic: str, payload: bytes):
    try:
        r = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None                                     # malformed JSON
    if not isinstance(r, dict) or any(k not in r for k in REQUIRED):
        return None

    # topic must match the payload: home/{room}/{appliance}/power
    parts = topic.split("/")
    if len(parts) != 4 or parts[1] != r["room"] or parts[2] != r["appliance"]:
        return None

    try:
        r["ts"] = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
        for k in ("power_w", "voltage_v", "current_a"):
            r[k] = float(r[k])
        r["seq"] = int(r["seq"])
    except (ValueError, TypeError, AttributeError):
        return None

    if r["power_w"] < 0 or r["power_w"] > MAX_WATTS.get(r["appliance"], 10_000):
        return None
    if not 90 <= r["voltage_v"] <= 140:
        return None
    return r


class GapFiller:
    """Uses seq numbers per device to drop duplicates and fill short gaps.

    process(r) returns the readings to pass on (oldest first):
      - []                 duplicate (same seq again, e.g. a QoS 1 redelivery)
      - [r]                normal reading, a seq reset, or a gap too long to fill
      - [f1, ..., fn, r]   1..MAX_GAP missing readings filled by linear
                           interpolation, each marked "filled": True
    """

    MAX_GAP = 3

    def __init__(self):
        self.last = {}                       # device_id -> last real reading
        self.stats = {"filled": 0, "duplicates": 0, "long_gaps": 0}

    def process(self, r):
        dev = r["device_id"]
        prev = self.last.get(dev)
        if prev is not None and r["seq"] == prev["seq"]:
            self.stats["duplicates"] += 1
            return []
        self.last[dev] = r
        # first reading, or seq went backwards (device/simulator restarted)
        if prev is None or r["seq"] < prev["seq"]:
            return [r]

        missing = r["seq"] - prev["seq"] - 1
        if missing == 0:
            return [r]
        if missing > self.MAX_GAP:
            self.stats["long_gaps"] += 1
            print(f"gap of {missing} readings on {dev} (seq {prev['seq']}..{r['seq']}), not filled")
            return [r]

        filled = []
        for i in range(1, missing + 1):
            f = i / (missing + 1)
            row = {k: r[k] for k in ("device_id", "room", "appliance")}
            row["seq"] = prev["seq"] + i
            row["ts"] = prev["ts"] + (r["ts"] - prev["ts"]) * f
            for k in ("power_w", "voltage_v", "current_a"):
                row[k] = round(prev[k] + (r[k] - prev[k]) * f, 2)
            row["filled"] = True
            filled.append(row)
        self.stats["filled"] += missing
        return filled + [r]
