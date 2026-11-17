import json
from datetime import datetime, timedelta, timezone

from cleaning import GapFiller, parse_reading

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


# ---- gap filling ----

T0 = datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc)


def rd(seq, watts):
    return {"device_id": "plug-refrigerator", "room": "kitchen", "appliance": "refrigerator",
            "ts": T0 + timedelta(seconds=5 * seq), "seq": seq,
            "power_w": watts, "voltage_v": 120.0, "current_a": watts / 120}


def test_consecutive_readings_pass_through():
    g = GapFiller()
    assert g.process(rd(1, 100)) == [rd(1, 100)]
    assert g.process(rd(2, 110)) == [rd(2, 110)]


def test_short_gap_is_interpolated():
    g = GapFiller()
    g.process(rd(1, 100))
    out = g.process(rd(4, 400))                  # seq 2 and 3 missing
    assert [r["seq"] for r in out] == [2, 3, 4]
    assert [r["power_w"] for r in out] == [200, 300, 400]
    assert out[0]["ts"] == T0 + timedelta(seconds=10)
    assert out[0]["filled"] and out[1]["filled"] and "filled" not in out[2]


def test_long_gap_not_filled():
    g = GapFiller()
    g.process(rd(1, 100))
    assert g.process(rd(10, 100)) == [rd(10, 100)]
    assert g.stats["long_gaps"] == 1


def test_duplicate_dropped():
    g = GapFiller()
    g.process(rd(5, 100))
    assert g.process(rd(5, 100)) == []


def test_seq_reset_after_restart():
    g = GapFiller()
    g.process(rd(500, 100))
    assert g.process(rd(1, 100)) == [rd(1, 100)]     # simulator restarted, seq back to 1
    assert g.process(rd(2, 100)) == [rd(2, 100)]
