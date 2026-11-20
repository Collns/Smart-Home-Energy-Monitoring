"""Generate labelled training / test data offline, without MQTT.  OWNER: Part 2

Runs the simulator's own power profiles (simulator/profiles.py) tick by tick and writes
  - readings in the same JSONL format the processor buffers (data/buffer_PowerRaw.jsonl)
  - injected faults in the same CSV format as the simulator (data/injected_faults.csv),
    plus a `visible_ticks` column: how many fault readings actually differ from normal.
A week of data takes seconds instead of ~1.5 h with the live pipeline at SPEED=120.
Use it to train and tune; do one live pipeline run for the final numbers in the report.

Run from the repo root (it needs simulator/profiles.py, so not inside the container):
    python processor/anomaly/generate.py --days 7 --out data/train.jsonl
    python processor/anomaly/generate.py --days 3 --fault-rate 0.0005 --seed 2 \\
        --out data/test.jsonl --faults-out data/test_faults.csv
"""
import argparse
import csv
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "simulator"))
from profiles import ALL_PROFILES  # noqa: E402

INTERVAL = timedelta(seconds=5)
HOME_TZ = ZoneInfo("America/Toronto")      # same default as the simulator (HOME_TIMEZONE)


def step(profile, t):
    """Same as Profile.step(), but also returns the power without the fault."""
    normal = watts = profile.base_power(t)
    if profile.fault:
        watts = profile.apply_fault(watts)
        profile.fault_ticks_left -= 1
        if profile.fault_ticks_left <= 0:
            profile.fault = None
            profile.fault_ticks_left = 0
    noise = random.gauss(0.0, max(1.0, watts * 0.02))
    return max(0.0, watts + noise), normal, watts


def generate(days, fault_rate, start, out, faults_out=None):
    ticks = int(timedelta(days=days) / INTERVAL)
    faults = []
    with open(out, "w") as f:
        for cls in ALL_PROFILES:
            p = cls()
            current = None                         # fault row being recorded
            for seq in range(1, ticks + 1):
                ts = start + INTERVAL * (seq - 1)
                if fault_rate and p.fault is None and random.random() < fault_rate:
                    n = random.randint(60, 360)    # same range as simulator.py
                    p.start_fault(n)
                    current = {"start_ts": ts.isoformat(), "appliance": p.appliance,
                               "fault": p.fault, "ticks": n, "visible_ticks": 0}
                    faults.append(current)
                in_fault = p.fault is not None
                watts, normal, faulted = step(p, ts.astimezone(HOME_TZ))
                if in_fault and abs(faulted - normal) > 0.1 * max(normal, 10):
                    current["visible_ticks"] += 1
                voltage = random.gauss(120.0, 1.5)
                f.write(json.dumps({
                    "device_id": f"plug-{p.appliance}", "room": p.room, "appliance": p.appliance,
                    "ts": ts.isoformat().replace("+00:00", "Z"), "seq": seq,
                    "power_w": round(watts, 2), "voltage_v": round(voltage, 2),
                    "current_a": round(watts / voltage, 3)}) + "\n")
    if faults_out:
        with open(faults_out, "w", newline="") as f:
            w = csv.DictWriter(f, ["start_ts", "appliance", "fault", "ticks", "visible_ticks"])
            w.writeheader()
            w.writerows(faults)
    return faults


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--fault-rate", type=float, default=0.0,
                    help="chance per reading that a fault starts (simulator FAULT_RATE)")
    ap.add_argument("--start", default="2026-11-02T00:00:00-05:00",
                    help="first reading (a Monday, midnight Toronto)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--faults-out")
    a = ap.parse_args(argv)
    random.seed(a.seed)
    start = datetime.fromisoformat(a.start).astimezone(timezone.utc)
    faults = generate(a.days, a.fault_rate, start, a.out, a.faults_out)
    print(f"wrote {a.out} ({a.days} days x {len(ALL_PROFILES)} appliances)"
          + (f", {len(faults)} faults -> {a.faults_out}" if a.faults_out else ""))


if __name__ == "__main__":
    main()
