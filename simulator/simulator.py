"""Six virtual smart plugs publishing electricity readings over MQTT. OWNER: Part 1.

One MQTT client runs per appliance. Readings are published at QoS 1 to
home/{room}/{appliance}/power; retained online/offline status uses the
corresponding /status topic.

Power-reading timestamps stay in UTC for the shared data pipeline, while
appliance behaviour follows the configured household time zone.
"""

import csv
import json
import os
import random
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import paho.mqtt.client as mqtt

from profiles import ALL_PROFILES


HOST = os.getenv("MQTT_HOST", "localhost")
USE_TLS = os.getenv("MQTT_TLS", "false").lower() == "true"
PORT = int(os.getenv("MQTT_PORT", "8883" if USE_TLS else "1883"))
CA_CERT = os.getenv("MQTT_CA_CERT", "/certs/ca.crt")
PLUG_PASSWORD = os.getenv("PLUG_PASSWORD", "")
INTERVAL = float(os.getenv("PUBLISH_INTERVAL_S", "5"))
SPEED = float(os.getenv("SPEED", "1"))
DROP_RATE = float(os.getenv("DROP_RATE", "0.01"))
MALFORMED_RATE = float(os.getenv("MALFORMED_RATE", "0.005"))
FAULT_RATE = float(os.getenv("FAULT_RATE", "0"))
TIMEZONE_NAME = os.getenv("HOME_TIMEZONE", "America/Toronto")

# Docker mounts /data. Running Python directly on a Mac uses the repo's data/.
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FAULT_LOG = (Path("/data/injected_faults.csv") if Path("/data").is_dir()
                     else ROOT / "data" / "injected_faults.csv")
FAULT_LOG = Path(os.getenv("FAULT_LOG", str(DEFAULT_FAULT_LOG)))

if INTERVAL <= 0 or SPEED <= 0:
    raise ValueError("PUBLISH_INTERVAL_S and SPEED must be greater than zero")
for name, rate in (("DROP_RATE", DROP_RATE), ("MALFORMED_RATE", MALFORMED_RATE),
                   ("FAULT_RATE", FAULT_RATE)):
    if not 0 <= rate <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
try:
    HOME_TZ = ZoneInfo(TIMEZONE_NAME)
except ZoneInfoNotFoundError as exc:
    raise RuntimeError(
        f"Unknown time zone {TIMEZONE_NAME!r}; install the tzdata package if needed"
    ) from exc

START_MONOTONIC = time.monotonic()
START_SIM = datetime.now(timezone.utc)
FAULT_LOG_LOCK = threading.Lock()
STOP = threading.Event()


def sim_now() -> datetime:
    """Return accelerated simulated UTC time; unaffected by wall-clock corrections."""
    elapsed = (time.monotonic() - START_MONOTONIC) * SPEED
    return START_SIM + timedelta(seconds=elapsed)


def log_fault(ts: datetime, appliance: str, fault: str, ticks: int) -> None:
    """Write ground-truth labels for ML evaluation, outside MQTT payloads."""
    with FAULT_LOG_LOCK:
        FAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
        new_file = not FAULT_LOG.exists() or FAULT_LOG.stat().st_size == 0
        with FAULT_LOG.open("a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            if new_file:
                writer.writerow(("start_ts", "appliance", "fault", "ticks"))
            writer.writerow((ts.isoformat(), appliance, fault, ticks))


def make_client(profile) -> mqtt.Client:
    client_id = f"plug-{profile.appliance}"
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=False,
    )
    if PLUG_PASSWORD:
        # ACL rules use the appliance name as this client's MQTT username.
        client.username_pw_set(profile.appliance, PLUG_PASSWORD)
    if USE_TLS:
        # The broker certificate must match MQTT_HOST and be signed by this CA.
        client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)

    status_topic = f"home/{profile.room}/{profile.appliance}/status"
    client.will_set(status_topic, "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[{client_id}] connection refused: {reason_code}", flush=True)
            return
        print(f"[{client_id}] connected: {reason_code}", flush=True)
        c.publish(status_topic, "online", qos=1, retain=True)

    client.on_connect = on_connect
    return client


def run_plug(profile) -> None:
    client = make_client(profile)
    status_topic = f"home/{profile.room}/{profile.appliance}/status"
    power_topic = f"home/{profile.room}/{profile.appliance}/power"

    # Retry initial connection if the broker is not yet ready.
    while not STOP.is_set():
        try:
            client.connect(HOST, PORT, keepalive=30)
            break
        except (OSError, TimeoutError) as exc:
            print(f"[{profile.appliance}] broker unavailable ({exc}); retrying", flush=True)
            STOP.wait(3)
    if STOP.is_set():
        return

    client.loop_start()
    seq = 0
    try:
        while not STOP.is_set():
            timestamp_utc = sim_now()
            household_time = timestamp_utc.astimezone(HOME_TZ)

            if FAULT_RATE and profile.fault is None and random.random() < FAULT_RATE:
                ticks = random.randint(60, 360)  # 5–30 simulated minutes.
                profile.start_fault(ticks)
                try:
                    log_fault(timestamp_utc, profile.appliance, profile.fault, ticks)
                    print(f"[{profile.appliance}] injected {profile.fault} ({ticks} readings)",
                          flush=True)
                except OSError as exc:
                    print(f"[{profile.appliance}] cannot write fault log: {exc}", flush=True)

            watts = profile.step(household_time)
            voltage = random.gauss(120.0, 1.5)
            seq += 1
            reading = {
                "device_id": f"plug-{profile.appliance}",
                "room": profile.room,
                "appliance": profile.appliance,
                "ts": timestamp_utc.isoformat().replace("+00:00", "Z"),
                "seq": seq,
                "power_w": round(watts, 2),
                "voltage_v": round(voltage, 2),
                "current_a": round(watts / voltage, 3),
            }

            if random.random() < DROP_RATE:
                # Intentionally missing sequence number (fault-injection test).
                pass
            elif random.random() < MALFORMED_RATE:
                client.publish(power_topic, '{"power_w": oops', qos=1)
            else:
                info = client.publish(power_topic, json.dumps(reading), qos=1)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    print(f"[{profile.appliance}] publish queued/failed: {mqtt.error_string(info.rc)}",
                          flush=True)

            # Interval specifies simulated seconds; SPEED accelerates real time.
            STOP.wait(INTERVAL / SPEED)
    finally:
        try:
            # A clean disconnect does not invoke the Last Will; mark offline explicitly.
            status_info = client.publish(status_topic, "offline", qos=1, retain=True)
            if status_info.rc == mqtt.MQTT_ERR_SUCCESS:
                status_info.wait_for_publish(timeout=2)
            client.disconnect()
        except (OSError, RuntimeError, ValueError):
            pass
        client.loop_stop()


def main() -> None:
    print(f"Simulator -> {HOST}:{PORT} tls={USE_TLS} speed={SPEED}x "
          f"home_tz={TIMEZONE_NAME}", flush=True)
    threads = [threading.Thread(target=run_plug, args=(profile_cls(),), daemon=True)
               for profile_cls in ALL_PROFILES]
    for thread in threads:
        thread.start()
    try:
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("Stopping virtual smart plugs...", flush=True)
    finally:
        STOP.set()
        for thread in threads:
            thread.join(timeout=4)


if __name__ == "__main__":
    main()
