"""Audit MQTT QoS 1 sequence gaps across a Mosquitto broker restart.

Run from the project root on the Mac while the six-plug simulator is running:
    python tests/broker_restart_test.py

Uses the processor's read-only MQTT subscription over verified TLS. Restarts
only the Mosquitto service. No secrets are printed or written to disk.
"""

import argparse
import json
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

import paho.mqtt.client as mqtt

EXPECTED = {
    "refrigerator", "microwave", "washing_machine",
    "water_heater", "air_conditioner", "television",
}


def read_processor_password() -> str:
    env_path = Path(".env")
    if not env_path.is_file():
        raise RuntimeError("Missing .env in the project root")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("PROCESSOR_PASSWORD="):
            password = raw.partition("=")[2].strip().strip('"').strip("'")
            if password:
                return password
    raise RuntimeError("PROCESSOR_PASSWORD is missing from .env")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=int, default=12,
                        help="Seconds to observe readings before restart (default: 12)")
    parser.add_argument("--after", type=int, default=45,
                        help="Seconds to observe readings after restart (default: 45)")
    args = parser.parse_args()
    if args.before < 5 or args.after < 10:
        parser.error("--before must be >= 5 and --after >= 10")

    observations = defaultdict(set)
    duplicates = defaultdict(int)
    pre_counts = defaultdict(int)
    post_counts = defaultdict(int)
    lock = threading.Lock()
    connected = threading.Event()
    failed = threading.Event()
    phase = ["pre"]

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"MQTT connection rejected: {reason_code}", flush=True)
            failed.set()
            return
        print("Observer connected over TLS; subscribing to power readings", flush=True)
        client.subscribe("home/+/+/power", qos=1)
        connected.set()

    def on_disconnect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"Observer disconnected during broker interruption: {reason_code}",
                  flush=True)

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            appliance, seq = data["appliance"], data["seq"]
            if appliance not in EXPECTED or not isinstance(seq, int) or seq < 1:
                return
        except (ValueError, KeyError, TypeError):
            return
        with lock:
            if seq in observations[appliance]:
                duplicates[appliance] += 1
            observations[appliance].add(seq)
            if phase[0] == "pre":
                pre_counts[appliance] += 1
            elif phase[0] == "post":
                post_counts[appliance] += 1

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"restart-audit-{uuid.uuid4().hex[:8]}",
        clean_session=False,
    )
    client.username_pw_set("processor", read_processor_password())
    client.tls_set(ca_certs="mosquitto/certs/ca.crt")
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    try:
        client.connect("localhost", 8883, keepalive=30)
        client.loop_start()
        if not connected.wait(10) or failed.is_set():
            print("FAIL: Observer could not authenticate and subscribe")
            return 1
        print(f"Observing for {args.before}s before the broker restart...", flush=True)
        time.sleep(args.before)

        with lock:
            seen_before = {name for name in EXPECTED if pre_counts[name] > 0}
        if seen_before != EXPECTED:
            missing = sorted(EXPECTED - seen_before)
            print(f"INCOMPLETE: No baseline readings from: {', '.join(missing)}")
            print("Verify the simulator is running with DROP_RATE=0 and MALFORMED_RATE=0")
            return 1

        with lock:
            phase[0] = "restart"
        print("Restarting Mosquitto now...", flush=True)
        subprocess.run(["docker", "compose", "restart", "mosquitto"],
                       check=True, timeout=40)
        with lock:
            phase[0] = "post"
        print(f"Observing for {args.after}s after the broker restart...", flush=True)
        time.sleep(args.after)

        print("\nAppliance          Before  After  Unique seq  Missing seq  Duplicates")
        print("-" * 74)
        all_complete = True
        any_gaps = False
        with lock:
            for appliance in sorted(EXPECTED):
                seqs = sorted(observations[appliance])
                count = len(seqs)
                missing_count = 0
                sample_missing = []
                for prev, curr in zip(seqs, seqs[1:]):
                    if curr > prev + 1:
                        missing_count += curr - prev - 1
                        sample_missing.extend(range(prev + 1, min(curr, prev + 6)))
                before = pre_counts[appliance]
                after = post_counts[appliance]
                duplicates_count = duplicates[appliance]
                print(f"{appliance:<19}{before:>5}{after:>7}{count:>12}"
                      f"{missing_count:>13}{duplicates_count:>12}")
                if missing_count:
                    any_gaps = True
                    print(f"  Missing {appliance} seq examples: {sample_missing[:12]}")
                if before < 1 or after < 2:
                    all_complete = False

        if not all_complete:
            print("\nINCOMPLETE: Need readings from all devices before AND after restart.")
            print("Repeat with --after 90 if devices reconnect slowly.")
            return 2
        if any_gaps:
            print("\nRESULT: One or more MQTT sequence gaps observed.")
            print("QoS 1 alone does not guarantee application-level zero loss.")
            return 2
        print("\nRESULT: No sequence gaps detected within the observed ranges.")
        print("This is an observational test, not proof against loss outside the range.")
        return 0
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    sys.exit(main())
