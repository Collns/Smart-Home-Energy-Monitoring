"""One-shot end-to-end durable MQTT outage test for the Smart Home simulator.

Run from project root on the Mac while the UPDATED simulator is running:
  python tests/broker_buffer_recovery_test.py --outage 20 --recovery 75

The test measures that all six appliances keep generating readings with
Mosquitto down, then confirms that the readings generated during the outage
are removed from the SQLite outbox after broker PUBACK on reconnect.
Never deletes/reinitializes the database; ensures broker is brought back up.
"""

import argparse
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

APPLIANCES = (
    "air_conditioner", "microwave", "refrigerator", "television",
    "washing_machine", "water_heater",
)
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "mqtt_outbox.sqlite3"


def snapshot():
    if not DB_PATH.is_file():
        raise RuntimeError(f"Outbox database missing: {DB_PATH}")
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        sequences = dict(db.execute(
            "SELECT appliance, last_seq FROM appliance_sequence"))
        counts = dict(db.execute(
            "SELECT appliance, COUNT(*) FROM pending_power GROUP BY appliance"))
        pending_by_seq = {name: set() for name in APPLIANCES}
        for name, seq in db.execute("SELECT appliance, seq FROM pending_power"):
            if name in pending_by_seq:
                pending_by_seq[name].add(seq)
    return sequences, counts, pending_by_seq


def command(*args):
    subprocess.run(args, cwd=ROOT, check=True, timeout=60)


def ensure_simulator_running():
    result = subprocess.run(
        ["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=smart-home-energy-monitoring",
         "--filter", "label=com.docker.compose.service=simulator"],
        cwd=ROOT, text=True, capture_output=True, check=True, timeout=15,
    )
    if not result.stdout.strip():
        raise RuntimeError("No running simulator found; start the updated simulator first")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outage", type=int, default=20)
    parser.add_argument("--recovery", type=int, default=75)
    args = parser.parse_args()
    if args.outage < 15 or args.recovery < 20:
        parser.error("Use --outage >= 15 and --recovery >= 20")

    broker_stopped = False
    try:
        ensure_simulator_running()
        command("docker", "compose", "up", "-d", "mosquitto")
        time.sleep(6)
        before_seq, _, _ = snapshot()
        if any(name not in before_seq for name in APPLIANCES):
            raise RuntimeError("Missing sequence data for one or more appliances")
        print("Baseline sequences:", before_seq, flush=True)

        print(f"\nStopping Mosquitto for {args.outage}s...", flush=True)
        command("docker", "compose", "stop", "mosquitto")
        broker_stopped = True
        time.sleep(args.outage)
        during_seq, during_counts, during_pending = snapshot()
        print("\nDURING OUTAGE (before broker restart)")
        generated = {}
        generation_pass = True
        buffering_pass = True
        for name in APPLIANCES:
            new = during_seq.get(name, 0) - before_seq[name]
            generated[name] = new
            # Some readings may have been queued right before the stop and already ACKed.
            # With DROP_RATE=0, outage-generated seq should be pending while offline.
            stored = sum(before_seq[name] < seq <= during_seq[name]
                         for seq in during_pending[name])
            print(f"  {name:<19} generated={new:>3} buffered={stored:>3}")
            generation_pass &= new >= 2
            buffering_pass &= stored >= max(0, new - 1)
        print("PASS: all generators advanced" if generation_pass
              else "FAIL: one or more generators stopped during outage")
        print("PASS: offline readings retained" if buffering_pass
              else "FAIL: offline readings missing from outbox")

        print("\nRestarting Mosquitto...", flush=True)
        command("docker", "compose", "up", "-d", "mosquitto")
        broker_stopped = False

        print("Checking that outage readings are acknowledged after reconnect...", flush=True)
        deadline = time.monotonic() + args.recovery
        while time.monotonic() < deadline:
            post_seq, pending_counts, post_pending = snapshot()
            old_pending = {
                name: sorted(seq for seq in post_pending[name]
                             if seq <= during_seq[name])
                for name in APPLIANCES
            }
            if all(not seqs for seqs in old_pending.values()):
                break
            time.sleep(2)

        old_pending = {
            name: sorted(seq for seq in post_pending[name] if seq <= during_seq[name])
            for name in APPLIANCES
        }
        print("\nAFTER RECONNECTION")
        for name in APPLIANCES:
            print(f"  {name:<19} pending_from_outage={len(old_pending[name]):>3} "
                  f"current_seq={post_seq.get(name, 0)}")
        recovered = all(not seqs for seqs in old_pending.values())
        # Verify the same simulator still generates new readings after recovery.
        time.sleep(12)
        final_seq, _, _ = snapshot()
        resumed = all(final_seq.get(name, 0) > post_seq.get(name, 0)
                      for name in APPLIANCES)
        print("\nSUMMARY")
        print(f"  Continued generating while offline: {'PASS' if generation_pass else 'FAIL'}")
        print(f"  Offline readings persisted:        {'PASS' if buffering_pass else 'FAIL'}")
        print(f"  Outage backlog acknowledged:       {'PASS' if recovered else 'FAIL'}")
        print(f"  Generating again after recovery:   {'PASS' if resumed else 'FAIL'}")
        if all((generation_pass, buffering_pass, recovered, resumed)):
            print("PASS: Durable outage/recovery test completed")
            print("Note: QoS 1 is at least once; consumers still need deduplication.")
            return 0
        return 2
    except (RuntimeError, OSError, sqlite3.Error,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}")
        return 1
    finally:
        if broker_stopped:
            print("Restoring Mosquitto...", flush=True)
            try:
                command("docker", "compose", "up", "-d", "mosquitto")
            except Exception as exc:
                print(f"WARNING: Could not restart broker: {exc}")


if __name__ == "__main__":
    sys.exit(main())
