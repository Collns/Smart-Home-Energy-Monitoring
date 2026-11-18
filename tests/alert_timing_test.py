"""Alert timing test (target: alert < 10 s after a threshold breach).  OWNER: Part 2

Measures, on the real pipeline (plug -> Mosquitto -> processor -> Mosquitto -> subscriber),
how long it takes from the reading that completes a threshold rule to the alert arriving
on home/alerts.

How: for each appliance, act as its plug and send readings above its shortest threshold
rule (e.g. TV > 250 W for 5 min). The readings carry timestamps 5 s apart but are sent
quickly, so a 5-min (or 1-h) rule is reached in seconds instead of waiting it out. All
readings except the last are sent first; then the clock starts, the LAST reading (the one
that completes the duration) is sent, and the clock stops when the alert arrives.
Delay = MQTT in + processing + MQTT out, measured with one clock on this machine.

Before running:
  - pipeline up: docker compose up -d
  - stop the simulator so it doesn't send readings for the same plugs:
        docker compose stop simulator
  - MONITOR_PASSWORD set in .env and ./scripts/create_mqtt_users.sh re-run (monitor
    account can read home/alerts), then: docker compose restart mosquitto
  - best with ADX_ENABLED=false: the test readings are stored like real ones
    (delete data/buffer_*.jsonl afterwards)

Run from the repo root:
    python tests/alert_timing_test.py                # 3 runs per appliance
    python tests/alert_timing_test.py --runs 5 --markdown
"""
import argparse
import json
import math
import os
import queue
import ssl
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "processor"))
from alerts import THRESHOLDS, _fmt  # noqa: E402
from cleaning import MAX_WATTS  # noqa: E402

ROOMS = {"refrigerator": "kitchen", "microwave": "kitchen", "washing_machine": "laundry",
         "water_heater": "utility", "air_conditioner": "living_room", "television": "living_room"}
TICK = timedelta(seconds=5)
TARGET_S = 10.0


def load_env(path):
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")   # last value wins, like Docker
    return env


def client(name, user, password, args):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=name, clean_session=True)
    c.username_pw_set(user, password)
    if args.tls:
        c.tls_set(ca_certs=args.ca, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    connected = []
    c.on_connect = lambda cl, ud, fl, rc, pr: connected.append(rc)
    c.connect(args.host, args.port, keepalive=30)
    c.loop_start()
    for _ in range(50):
        if connected:
            break
        time.sleep(0.1)
    if not connected or connected[0].is_failure:
        sys.exit(f"{name}: could not connect as '{user}' ({connected[0] if connected else 'timeout'})")
    return c


class Plug:
    """Sends readings for one appliance with its own increasing seq and timestamps."""

    def __init__(self, appliance, password, args, clock):
        self.appliance, self.clock = appliance, clock
        self.topic = f"home/{ROOMS[appliance]}/{appliance}/power"
        self.seq = int(time.time()) * 1000            # above anything the simulator sent
        self.c = client(f"timing-test-{appliance}", appliance, password, args)

    def send(self, watts):
        self.seq += 1
        self.clock[0] += TICK
        reading = {"device_id": f"plug-{self.appliance}", "room": ROOMS[self.appliance],
                   "appliance": self.appliance,
                   "ts": self.clock[0].isoformat().replace("+00:00", "Z"), "seq": self.seq,
                   "power_w": round(watts, 2), "voltage_v": 120.0, "current_a": round(watts / 120, 3)}
        self.c.publish(self.topic, json.dumps(reading), qos=1).wait_for_publish(timeout=5)


def run_once(plug, limit, duration, alerts):
    watts = min(limit * 1.2, MAX_WATTS[plug.appliance] * 0.95)
    n = math.ceil(duration / TICK)                    # reading n completes the duration
    for _ in range(3):
        plug.send(0.0)                                # reset the rule
    for _ in range(n):                                # readings 0 .. n-1: not yet long enough
        plug.send(watts)
    time.sleep(2)                                     # let the processor catch up
    early = drain(alerts, plug.appliance)
    t0 = time.monotonic()
    plug.send(watts)                                  # reading n: breach completed
    deadline = t0 + 30
    while time.monotonic() < deadline:
        try:
            t, alert = alerts.get(timeout=deadline - time.monotonic())
        except queue.Empty:
            break
        if alert.get("appliance") == plug.appliance and alert.get("type") == "threshold":
            plug.send(0.0)
            return t - t0, alert.get("message", ""), early
    plug.send(0.0)
    return None, "no alert within 30 s", early


def drain(alerts, appliance):
    early = 0
    while True:
        try:
            _, a = alerts.get_nowait()
        except queue.Empty:
            return early
        early += a.get("appliance") == appliance and a.get("type") == "threshold"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure threshold alert delay on the live pipeline")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8883)
    ap.add_argument("--no-tls", dest="tls", action="store_false")
    ap.add_argument("--ca", default=str(ROOT / "mosquitto/certs/ca.crt"))
    ap.add_argument("--runs", type=int, default=3, help="runs per appliance")
    ap.add_argument("--appliances", nargs="*", default=list(THRESHOLDS))
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args(argv)

    env = {**load_env(ROOT / ".env"), **os.environ}
    if not env.get("MONITOR_PASSWORD"):
        sys.exit("MONITOR_PASSWORD missing: add it to .env and re-run scripts/create_mqtt_users.sh")

    alerts = queue.Queue()
    mon = client("timing-test-monitor", "monitor", env["MONITOR_PASSWORD"], args)
    mon.on_message = lambda c, u, m: alerts.put((time.monotonic(), json.loads(m.payload)))
    mon.subscribe("home/alerts", qos=2)
    time.sleep(1)

    clock = [datetime.now(timezone.utc)]
    rows = []
    for appliance in args.appliances:
        limit, duration = min(THRESHOLDS[appliance], key=lambda rule: rule[1])
        pw = env.get(f"PLUG_{appliance.upper()}_PASSWORD") or env.get("PLUG_PASSWORD")
        plug = Plug(appliance, pw, args, clock)
        for i in range(args.runs):
            delay, msg, early = run_once(plug, limit, duration, alerts)
            rows.append({"appliance": appliance, "rule": f"> {limit:g} W for {_fmt(duration)}",
                         "run": i + 1, "delay_s": delay, "early": early, "message": msg})
            shown = f"{delay:.3f} s" if delay is not None else "FAIL"
            print(f"{appliance:16s} run {i + 1}: {shown:9s} {msg}"
                  + (f"  (!! {early} alert(s) BEFORE the breach)" if early else ""), flush=True)
        plug.c.loop_stop()
    mon.loop_stop()

    delays = [r["delay_s"] for r in rows if r["delay_s"] is not None]
    failed = len(rows) - len(delays) + sum(1 for r in rows if r["early"])
    if delays:
        p95 = sorted(delays)[math.ceil(0.95 * len(delays)) - 1]          # nearest rank
        summary = (f"{len(delays)}/{len(rows)} alerts | p50 {statistics.median(delays):.3f} s | "
                   f"p95 {p95:.3f} s | max {max(delays):.3f} s")
    else:
        summary = "no alerts received"
    ok = delays and not failed and max(delays) < TARGET_S
    print(f"\n{summary} -> {'PASS' if ok else 'FAIL'} (target < {TARGET_S:g} s)")

    if args.markdown:
        print("\n| Run | Appliance | Rule | Alert delay |\n|---|---|---|---|")
        for i, r in enumerate(rows, 1):
            d = f"{r['delay_s']:.3f} s" if r["delay_s"] is not None else "no alert"
            print(f"| {i} | {r['appliance']} | {r['rule']} | {d} |")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
