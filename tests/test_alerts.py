from datetime import datetime, timedelta, timezone

from alerts import ThresholdTracker


def reading(minutes, watts):
    t0 = datetime(2026, 11, 4, 15, tzinfo=timezone.utc)
    return {"appliance": "air_conditioner", "ts": t0 + timedelta(minutes=minutes), "power_w": watts}


def test_ac_alert_after_30_min():
    t = ThresholdTracker()
    assert t.check(reading(0, 2100)) is None
    assert t.check(reading(29, 2100)) is None
    alert = t.check(reading(30, 2100))
    assert alert and alert["type"] == "threshold"
    assert t.check(reading(31, 2100)) is None          # no duplicate


def test_resets_when_below():
    t = ThresholdTracker()
    t.check(reading(0, 2100))
    t.check(reading(20, 1500))
    assert t.check(reading(31, 2100)) is None
