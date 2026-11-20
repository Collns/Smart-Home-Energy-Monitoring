"""Six MQTT smart plugs with durable, acknowledged QoS 1 power readings.

OWNER: Part 1. Every reading is saved to a local SQLite outbox before
publishing. Only a successful MQTT PUBACK removes it. Sequence numbers survive
both broker restarts and simulator restarts.

Note: QoS 1 is at least once, not exactly once. A retry can create a duplicate;
consumers should deduplicate using (device_id, seq).
"""

import csv
import contextlib
import json
import os
import signal
import faulthandler
import random
import sqlite3
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
INTERVAL = float(os.getenv("PUBLISH_INTERVAL_S", "5"))
SPEED = float(os.getenv("SPEED", "1"))
DROP_RATE = float(os.getenv("DROP_RATE", "0.01"))
MALFORMED_RATE = float(os.getenv("MALFORMED_RATE", "0.005"))
FAULT_RATE = float(os.getenv("FAULT_RATE", "0"))
TIMEZONE_NAME = os.getenv("HOME_TIMEZONE", "America/Toronto")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path("/data") if Path("/data").is_dir() else ROOT / "data"
FAULT_LOG = Path(os.getenv("FAULT_LOG", str(DATA_DIR / "injected_faults.csv")))
OUTBOX_PATH = Path(os.getenv("MQTT_OUTBOX_DB", str(DATA_DIR / "mqtt_outbox.sqlite3")))

if INTERVAL <= 0 or SPEED <= 0:
    raise ValueError("PUBLISH_INTERVAL_S and SPEED must be greater than zero")
for name, rate in (("DROP_RATE", DROP_RATE), ("MALFORMED_RATE", MALFORMED_RATE),
                   ("FAULT_RATE", FAULT_RATE)):
    if not 0 <= rate <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
try:
    HOME_TZ = ZoneInfo(TIMEZONE_NAME)
except ZoneInfoNotFoundError as exc:
    raise RuntimeError(f"Unknown time zone {TIMEZONE_NAME!r}") from exc

START_MONOTONIC = time.monotonic()
START_SIM = datetime.now(timezone.utc)
FAULT_LOG_LOCK = threading.Lock()
STOP = threading.Event()


def sim_now() -> datetime:
    """Return accelerated UTC time for data storage and timestamps."""
    return START_SIM + timedelta(seconds=(time.monotonic() - START_MONOTONIC) * SPEED)


def log_fault(ts: datetime, appliance: str, fault: str, ticks: int) -> None:
    with FAULT_LOG_LOCK:
        FAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
        new = not FAULT_LOG.exists() or FAULT_LOG.stat().st_size == 0
        with FAULT_LOG.open("a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            if new:
                writer.writerow(("start_ts", "appliance", "fault", "ticks"))
            writer.writerow((ts.isoformat(), appliance, fault, ticks))


def appliance_password(appliance: str) -> str:
    key = f"PLUG_{appliance.upper()}_PASSWORD"
    password = os.getenv(key)
    if not password:
        raise RuntimeError(f"Missing {key}; load your local .env before starting")
    return password


class DurableOutbox:
    """Durable SQLite FIFO with independent, short-lived transactions.

    Do not share a sqlite3.Connection among the twelve appliance workers.
    SQLite serializes short write transactions; no process-wide Python lock
    can stall all generators if one worker blocks.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS appliance_sequence (
                    appliance TEXT PRIMARY KEY,
                    last_seq INTEGER NOT NULL
                )""")
            db.execute("""
                CREATE TABLE IF NOT EXISTS pending_power (
                    appliance TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (appliance, seq)
                )""")
            db.commit()

    @contextlib.contextmanager
    def _connection(self, write: bool = False):
        # Independent connection per operation, always closed even on errors.
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA synchronous=FULL")
            if write:
                db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                if write:
                    db.rollback()
                raise
            else:
                if write:
                    db.commit()
        finally:
            db.close()

    @staticmethod
    def _reserve_sequence(db, appliance: str) -> int:
        row = db.execute(
            "SELECT last_seq FROM appliance_sequence WHERE appliance=?",
            (appliance,),
        ).fetchone()
        seq = (row[0] if row else 0) + 1
        db.execute("""
            INSERT INTO appliance_sequence (appliance, last_seq)
            VALUES (?, ?) ON CONFLICT(appliance)
            DO UPDATE SET last_seq=excluded.last_seq
        """, (appliance, seq))
        return seq

    def enqueue(self, appliance: str, topic: str, reading: dict) -> int:
        """Atomically assign a durable sequence and save before publishing."""
        with self._connection(write=True) as db:
            seq = self._reserve_sequence(db, appliance)
            payload = json.dumps({**reading, "seq": seq}, separators=(",", ":"))
            db.execute("""
                INSERT INTO pending_power (appliance, seq, topic, payload)
                VALUES (?, ?, ?, ?)
            """, (appliance, seq, topic, payload))
        return seq

    def skip(self, appliance: str) -> int:
        """Intentionally create a sequence gap for fault-injection tests."""
        with self._connection(write=True) as db:
            return self._reserve_sequence(db, appliance)

    def oldest(self, appliance: str):
        with self._connection() as db:
            return db.execute("""
                SELECT seq, topic, payload FROM pending_power
                WHERE appliance=? ORDER BY seq LIMIT 1
            """, (appliance,)).fetchone()

    def acknowledge(self, appliance: str, seq: int) -> None:
        with self._connection(write=True) as db:
            db.execute(
                "DELETE FROM pending_power WHERE appliance=? AND seq=?",
                (appliance, seq),
            )

    def pending_count(self, appliance: str) -> int:
        with self._connection() as db:
            return db.execute(
                "SELECT COUNT(*) FROM pending_power WHERE appliance=?",
                (appliance,),
            ).fetchone()[0]

    def snapshot(self):
        """Return current sequences and backlog for lightweight monitoring."""
        with self._connection() as db:
            return db.execute("""
                SELECT s.appliance, s.last_seq, COUNT(p.seq)
                FROM appliance_sequence AS s
                LEFT JOIN pending_power AS p ON p.appliance=s.appliance
                GROUP BY s.appliance, s.last_seq
                ORDER BY s.appliance
            """).fetchall()

    def close(self) -> None:
        # Each transaction already closes its connection.
        pass


def make_client(profile, connected: threading.Event) -> mqtt.Client:
    client_id = f"plug-{profile.appliance}"
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=False,
    )
    client.username_pw_set(profile.appliance, appliance_password(profile.appliance))
    if USE_TLS:
        client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)

    status_topic = f"home/{profile.room}/{profile.appliance}/status"
    client.will_set(status_topic, "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[{client_id}] connection refused: {reason_code}", flush=True)
            connected.clear()
            return
        connected.set()
        print(f"[{client_id}] connected: {reason_code}", flush=True)
        c.publish(status_topic, "online", qos=1, retain=True)

    def on_disconnect(c, userdata, flags, reason_code, properties):
        connected.clear()
        if not STOP.is_set():
            print(f"[{client_id}] disconnected: {reason_code}", flush=True)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    return client


def deliver_pending(profile, client: mqtt.Client, connected: threading.Event,
                    outbox: DurableOutbox) -> None:
    """Publish saved readings in order; delete only after MQTT PUBACK."""
    name = profile.appliance
    while not STOP.is_set():
        if not connected.wait(timeout=1):
            continue
        try:
            pending = outbox.oldest(name)
        except sqlite3.Error as exc:
            print(f"[{name}] SQLite read retry: {exc}", flush=True)
            STOP.wait(1)
            continue
        if pending is None:
            STOP.wait(0.2)
            continue
        seq, topic, payload = pending
        info = client.publish(topic, payload, qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[{name}] publish not queued: {mqtt.error_string(info.rc)}", flush=True)
            STOP.wait(1)
            continue
        try:
            info.wait_for_publish(timeout=3)
            acknowledged = info.is_published()
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"[{name}] PUBACK pending for seq={seq}: {exc}", flush=True)
            acknowledged = False
        if acknowledged:
            try:
                outbox.acknowledge(name, seq)
            except sqlite3.Error as exc:
                # The durable row remains. Retry may redeliver a duplicate,
                # which is allowed under QoS 1 and needs consumer deduplication.
                print(f"[{name}] SQLite ACK retry for seq={seq}: {exc}", flush=True)
                STOP.wait(1)
        else:
            # Same (device_id, seq) may be resent: MQTT QoS 1 allows duplicates.
            STOP.wait(1)


def run_plug(profile, outbox: DurableOutbox) -> None:
    connected = threading.Event()
    client = make_client(profile, connected)
    status_topic = f"home/{profile.room}/{profile.appliance}/status"
    power_topic = f"home/{profile.room}/{profile.appliance}/power"

    # Begin generation immediately, even if the broker is already offline.
    # Paho's network loop handles initial connection and automatic reconnection.
    client.connect_async(HOST, PORT, keepalive=30)
    client.loop_start()
    sender = threading.Thread(
        target=deliver_pending,
        args=(profile, client, connected, outbox),
        daemon=True,
    )
    sender.start()
    try:
        while not STOP.is_set():
            timestamp_utc = sim_now()
            household_time = timestamp_utc.astimezone(HOME_TZ)
            if FAULT_RATE and profile.fault is None and random.random() < FAULT_RATE:
                ticks = random.randint(60, 360)
                profile.start_fault(ticks)
                try:
                    log_fault(timestamp_utc, profile.appliance, profile.fault, ticks)
                    print(f"[{profile.appliance}] injected {profile.fault} ({ticks} readings)",
                          flush=True)
                except OSError as exc:
                    print(f"[{profile.appliance}] cannot write fault log: {exc}", flush=True)

            watts = profile.step(household_time)
            voltage = random.gauss(120.0, 1.5)
            reading = {
                "device_id": f"plug-{profile.appliance}",
                "room": profile.room,
                "appliance": profile.appliance,
                "ts": timestamp_utc.isoformat().replace("+00:00", "Z"),
                "power_w": round(watts, 2),
                "voltage_v": round(voltage, 2),
                "current_a": round(watts / voltage, 3),
            }

            # Choose the fault-injection action just once. If SQLite is busy,
            # retry saving THIS reading rather than changing its outcome.
            roll = random.random()
            action = "drop" if roll < DROP_RATE else (
                "malformed" if roll < DROP_RATE + (1 - DROP_RATE) * MALFORMED_RATE
                else "save"
            )
            while not STOP.is_set():
                try:
                    if action == "drop":
                        outbox.skip(profile.appliance)
                    elif action == "malformed":
                        outbox.skip(profile.appliance)
                        if connected.is_set():
                            client.publish(power_topic, '{"power_w": oops', qos=1)
                    else:
                        outbox.enqueue(profile.appliance, power_topic, reading)
                    break
                except sqlite3.Error as exc:
                    print(f"[{profile.appliance}] SQLite save retry: {exc}", flush=True)
                    STOP.wait(1)
            STOP.wait(INTERVAL / SPEED)
    finally:
        sender.join(timeout=6)
        try:
            pending = outbox.pending_count(profile.appliance)
            if pending:
                print(f"[{profile.appliance}] saved {pending} unacknowledged readings for next run",
                      flush=True)
        except sqlite3.Error as exc:
            print(f"[{profile.appliance}] cannot count pending readings: {exc}", flush=True)
        try:
            status_info = client.publish(status_topic, "offline", qos=1, retain=True)
            if status_info.rc == mqtt.MQTT_ERR_SUCCESS:
                status_info.wait_for_publish(timeout=2)
            client.disconnect()
        except (OSError, RuntimeError, ValueError):
            pass
        client.loop_stop()


def main() -> None:
    profiles = [profile_cls() for profile_cls in ALL_PROFILES]
    for profile in profiles:
        appliance_password(profile.appliance)
    outbox = DurableOutbox(OUTBOX_PATH)
    print(f"Simulator -> {HOST}:{PORT} tls={USE_TLS} speed={SPEED}x "
          f"home_tz={TIMEZONE_NAME} durable_outbox={OUTBOX_PATH}", flush=True)
    threads = [
        threading.Thread(target=run_plug, args=(profile, outbox), daemon=True)
        for profile in profiles
    ]
    try:
        if hasattr(signal, "SIGUSR1"):
            # Linux container: `docker kill --signal=SIGUSR1 <container>`
            # prints live Python stacks to stderr without stopping the process.
            faulthandler.register(signal.SIGUSR1, all_threads=True)
        for thread in threads:
            thread.start()
        last_snapshot = None
        last_progress_at = time.monotonic()
        next_check = 0.0
        while not STOP.is_set():
            if any(not thread.is_alive() for thread in threads):
                raise RuntimeError("An appliance worker exited unexpectedly")
            now = time.monotonic()
            if now >= next_check:
                try:
                    snapshot = outbox.snapshot()
                    state = tuple((appliance, seq) for appliance, seq, _ in snapshot)
                    if state != last_snapshot:
                        last_snapshot = state
                        last_progress_at = now
                    elif now - last_progress_at >= max(30, 3 * INTERVAL / SPEED):
                        print("WARNING: Generation stalled for 30+ seconds; "
                              f"outbox={snapshot}", flush=True)
                        last_progress_at = now
                except sqlite3.Error as exc:
                    print(f"WARNING: Outbox health check failed: {exc}", flush=True)
                next_check = now + 10
            STOP.wait(0.5)
    except KeyboardInterrupt:
        print("Stopping virtual smart plugs...", flush=True)
    finally:
        STOP.set()
        for thread in threads:
            thread.join(timeout=10)
        outbox.close()


if __name__ == "__main__":
    main()
