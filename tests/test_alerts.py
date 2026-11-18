from datetime import datetime, timedelta, timezone

from alerts import StatusTracker, ThresholdTracker


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

STATUS = "home/kitchen/refrigerator/status"


def test_offline_fires_alert():
    alert = StatusTracker().check(STATUS, "offline")
    assert alert["type"] == "offline" and alert["appliance"] == "refrigerator"


def test_offline_not_repeated():
    s = StatusTracker()
    assert s.check(STATUS, "offline")
    assert s.check(STATUS, "offline") is None         # retained / duplicate message


def test_fires_again_after_coming_back_online():
    s = StatusTracker()
    s.check(STATUS, "offline")
    assert s.check(STATUS, "online") is None
    assert s.check(STATUS, "offline")


def test_garbage_status_ignored():
    assert StatusTracker().check(STATUS, "banana") is None


# ---- thresholds for every appliance ----
def at(appliance, minutes, watts):
    t0 = datetime(2026, 11, 4, 15, tzinfo=timezone.utc)
    return {"appliance": appliance, "ts": t0 + timedelta(minutes=minutes), "power_w": watts}


def test_every_appliance_has_a_rule():
    from alerts import THRESHOLDS
    assert set(THRESHOLDS) == {"refrigerator", "microwave", "washing_machine",
                               "water_heater", "air_conditioner", "television"}


def test_microwave_left_running():
    t = ThresholdTracker()
    assert t.check(at("microwave", 0, 1100)) is None
    alert = t.check(at("microwave", 10, 1100))
    assert alert and alert["message"] == "microwave above 900 W for 10 min"


def test_washer_two_rules_fire_separately():
    t = ThresholdTracker()
    fired = [t.check(at("washing_machine", m, 1200)) for m in range(0, 6)]    # 1200 W, 5 min
    fired += [t.check(at("washing_machine", m, 500)) for m in range(6, 121)]  # still on at 2 h
    messages = [a["message"] for a in fired if a]
    assert messages == ["washing_machine above 1000 W for 5 min",
                        "washing_machine above 50 W for 2 h"]


def test_rules_tripping_together_both_fire():
    t = ThresholdTracker()
    t.check(at("television", 0, 300))
    first = t.check(at("television", 480, 300))            # 5 min and 8 h rules both due
    second = t.check(at("television", 481, 300))
    assert {first["message"], second["message"]} == {
        "television above 250 W for 5 min", "television above 50 W for 8 h"}


def test_no_false_alarms_on_a_normal_week():
    """A week of the simulator's normal profiles (no faults) must not trip any threshold."""
    import random
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parents[1] / "simulator"))
    from profiles import ALL_PROFILES

    random.seed(1)
    t = ThresholdTracker()
    start = datetime(2026, 11, 2, tzinfo=timezone.utc)
    alerts = []
    for cls in ALL_PROFILES:
        p = cls()
        for i in range(7 * 24 * 720):                       # 5 s readings for 7 days
            ts = start + timedelta(seconds=5 * i)
            a = t.check({"appliance": p.appliance, "ts": ts, "power_w": p.step(ts)})
            if a:
                alerts.append(a)
    assert alerts == []
