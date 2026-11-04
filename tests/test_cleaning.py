import json

from cleaning import parse_reading

TOPIC = "home/kitchen/refrigerator/power"
GOOD = {"device_id": "plug-refrigerator", "room": "kitchen", "appliance": "refrigerator",
        "ts": "2026-11-04T18:30:05Z", "seq": 1, "power_w": 150.0,
        "voltage_v": 120.1, "current_a": 1.25}


def enc(d):
    return json.dumps(d).encode()


def test_good_reading_passes():
    r = parse_reading(TOPIC, enc(GOOD))
    assert r is not None and r["power_w"] == 150.0


def test_malformed_json_dropped():
    assert parse_reading(TOPIC, b'{"power_w": oops') is None


def test_negative_power_dropped():
    assert parse_reading(TOPIC, enc({**GOOD, "power_w": -5})) is None


def test_out_of_range_dropped():
    assert parse_reading(TOPIC, enc({**GOOD, "power_w": 99999})) is None


def test_topic_payload_mismatch_dropped():
    assert parse_reading("home/kitchen/microwave/power", enc(GOOD)) is None


def test_missing_field_dropped():
    bad = dict(GOOD)
    del bad["voltage_v"]
    assert parse_reading(TOPIC, enc(bad)) is None
