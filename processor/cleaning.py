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


# TODO Part 2: gap filling – track last seq per device; if a short gap (<= 3 readings)
# is detected, forward-fill / interpolate before aggregating.
