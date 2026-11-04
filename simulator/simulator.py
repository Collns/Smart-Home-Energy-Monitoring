"""Smart-plug simulator: one thread + one MQTT client per appliance.  OWNER: Part 1

Publishes to home/{room}/{appliance}/power every PUBLISH_INTERVAL_S (QoS 1).
Sets a retained Last Will on home/{room}/{appliance}/status.

TODO Part 1:
  - per-plug credentials (username = appliance name, see mosquitto/config/acl)
  - turn on TLS (MQTT_TLS=true, port 8883)
  - tune drop / malformed / fault rates
"""
import json
import os
import random
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

from profiles import ALL_PROFILES

HOST = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
USE_TLS = os.getenv("MQTT_TLS", "false").lower() == "true"
CA_CERT = os.getenv("MQTT_CA_CERT", "/certs/ca.crt")
PLUG_PASSWORD = os.getenv("PLUG_PASSWORD", "")
INTERVAL = float(os.getenv("PUBLISH_INTERVAL_S", "5"))
SPEED = float(os.getenv("SPEED", "1"))
DROP_RATE = float(os.getenv("DROP_RATE", "0.01"))
MALFORMED_RATE = float(os.getenv("MALFORMED_RATE", "0.005"))
FAULT_RATE = float(os.getenv("FAULT_RATE", "0"))
FAULT_LOG = os.getenv("FAULT_LOG", "/data/injected_faults.csv")

START_REAL = time.time()
START_SIM = datetime.now(timezone.utc)
fault_log_lock = threading.Lock()


def sim_now() -> datetime:
    """Simulated time. With SPEED>1 time runs faster (for generating training data)."""
    return START_SIM + timedelta(seconds=(time.time() - START_REAL) * SPEED)


def log_fault(ts, appliance, fault, ticks):
    with fault_log_lock:
        new = not os.path.exists(FAULT_LOG)
        with open(FAULT_LOG, "a") as f:
            if new:
                f.write("start_ts,appliance,fault,ticks\n")
            f.write(f"{ts.isoformat()},{appliance},{fault},{ticks}\n")


def make_client(profile) -> mqtt.Client:
    client_id = f"plug-{profile.appliance}"
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                    clean_session=False)                       # persistent session
    if PLUG_PASSWORD:
        c.username_pw_set(profile.appliance, PLUG_PASSWORD)
    if USE_TLS:
        c.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    status = f"home/{profile.room}/{profile.appliance}/status"
    c.will_set(status, "offline", qos=1, retain=True)           # Last Will
    c.reconnect_delay_set(min_delay=1, max_delay=60)            # backoff

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"[{client_id}] connected: {reason_code}")
        client.publish(status, "online", qos=1, retain=True)

    c.on_connect = on_connect
    return c


def run_plug(profile):
    client = make_client(profile)
    while True:
        try:
            client.connect(HOST, PORT, keepalive=30)
            break
        except OSError as e:
            print(f"[{profile.appliance}] broker not reachable ({e}), retrying...")
            time.sleep(3)
    client.loop_start()

    topic = f"home/{profile.room}/{profile.appliance}/power"
    seq = 0
    while True:
        t = sim_now()
        if FAULT_RATE and not profile.fault and random.random() < FAULT_RATE:
            ticks = random.randint(60, 360)
            profile.start_fault(ticks)
            log_fault(t, profile.appliance, profile.fault, ticks)

        watts = profile.step(t)
        voltage = random.gauss(120.0, 1.5)
        seq += 1
        reading = {
            "device_id": f"plug-{profile.appliance}",
            "room": profile.room,
            "appliance": profile.appliance,
            "ts": t.isoformat().replace("+00:00", "Z"),
            "seq": seq,
            "power_w": round(watts, 2),
            "voltage_v": round(voltage, 2),
            "current_a": round(watts / voltage, 3),
        }

        if random.random() < DROP_RATE:
            pass                                    # simulated packet loss
        elif random.random() < MALFORMED_RATE:
            client.publish(topic, '{"power_w": oops', qos=1)   # simulated bad data
        else:
            client.publish(topic, json.dumps(reading), qos=1)

        time.sleep(INTERVAL / SPEED if SPEED > 1 else INTERVAL)


def main():
    print(f"Simulator -> {HOST}:{PORT} tls={USE_TLS} speed={SPEED}x")
    threads = [threading.Thread(target=run_plug, args=(p(),), daemon=True) for p in ALL_PROFILES]
    for th in threads:
        th.start()
    for th in threads:
        th.join()


if __name__ == "__main__":
    main()
