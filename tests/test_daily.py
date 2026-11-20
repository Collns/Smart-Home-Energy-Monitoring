from datetime import datetime, timedelta, timezone

from daily import DailyEnergy

T0 = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)


def rd(seconds, watts, appliance="television"):
    return {"appliance": appliance, "ts": T0 + timedelta(seconds=seconds), "power_w": watts}


def test_constant_load_for_an_hour(tmp_path):
    d = DailyEnergy(tmp_path / "daily.csv")
    for s in range(0, 3601, 5):                             # 1000 W for 1 h
        d.add(rd(s, 1000))
    assert d.today() == {"television": 1.0}


def test_long_gap_not_counted(tmp_path):
    d = DailyEnergy(tmp_path / "daily.csv")
    d.add(rd(0, 1000))
    d.add(rd(3600, 1000))                                   # 1 h gap -> only 60 s counted
    assert d.today()["television"] == round(1000 * 60 / 3600 / 1000, 3)


def test_day_rollover_writes_csv(tmp_path):
    path = tmp_path / "daily.csv"
    d = DailyEnergy(path)
    for s in range(0, 86400, 5):                            # 100 W all day = 2.4 kWh
        assert d.add(rd(s, 100)) is None
    done = d.add(rd(86400, 100))
    assert done == (T0.date(), "television", 2.4)
    assert path.read_text().splitlines() == ["day,appliance,kwh", "2026-11-04,television,2.4"]
    assert d.today() == {"television": 0.0}


def test_appliances_tracked_separately(tmp_path):
    d = DailyEnergy(tmp_path / "daily.csv")
    for s in range(0, 3601, 5):
        d.add(rd(s, 1000, "television"))
        d.add(rd(s, 500, "microwave"))
    assert d.today() == {"television": 1.0, "microwave": 0.5}
