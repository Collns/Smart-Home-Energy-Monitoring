"""Real-time processing service.  OWNER: Part 2

MQTT home/+/+/power  -> clean -> ADX PowerRaw
                     -> threshold + ML checks -> home/alerts (QoS 2) + ADX Alerts
1-min averages and hourly energy are ADX materialized views (adx/03_views.kql).
"""
import json
import os
import ssl

import paho.mqtt.client as mqtt

from adx_writer import AdxWriter
from alerts import StatusTracker, ThresholdTracker
from anomaly.detector import AnomalyDetector
from cleaning import GapFiller, parse_reading
from daily import DailyEnergy

HOST = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
USE_TLS = os.getenv("MQTT_TLS", "false").lower() == "true"
CA_CERT = os.getenv("MQTT_CA_CERT", "/certs/ca.crt")
USER = os.getenv("PROCESSOR_USER")
PASSWORD = os.getenv("PROCESSOR_PASSWORD")
# Turn off for the broker-restart / Azure-outage tests, so lost readings are not hidden
GAP_FILL = os.getenv("GAP_FILL", "true").lower() == "true"

writer = AdxWriter()
thresholds = ThresholdTracker()
statuses = StatusTracker()
detector = AnomalyDetector()
gaps = GapFiller()
daily = DailyEnergy()
stats = {"ok": 0, "dropped": 0}


def publish_alert(client, alert):
    client.publish("home/alerts", json.dumps(alert), qos=2)
    writer.write("Alerts", alert)
    print("ALERT", alert)


def on_connect(client, userdata, flags, reason_code, properties):
    print("processor connected:", reason_code)
    client.subscribe([("home/+/+/power", 1), ("home/+/+/status", 1)])


def on_message(client, userdata, msg):
    if msg.topic.endswith("/status"):
        status = msg.payload.decode(errors="replace")
        print(f"device status {msg.topic} = {status}" + (" (retained)" if msg.retain else ""))
        alert = statuses.check(msg.topic, status, retained=msg.retain)
        if alert:
            publish_alert(client, alert)
        return

    r = parse_reading(msg.topic, msg.payload)
    if r is None:
        stats["dropped"] += 1
        return
    stats["ok"] += 1
    for reading in (gaps.process(r) if GAP_FILL else [r]):
        handle_reading(client, reading)

    if stats["ok"] % 100 == 0:
        print(f"processed={stats['ok']} dropped={stats['dropped']} {gaps.stats}")
        print(f"kWh today: {daily.today()}")


def handle_reading(client, r):
    writer.write("PowerRaw", r)
    daily.add(r)
    alert = thresholds.check(r)
    if alert:
        publish_alert(client, alert)
    alert = detector.check(r)
    if alert:
        publish_alert(client, alert)


def main():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="processor", clean_session=False)
    if USER:
        c.username_pw_set(USER, PASSWORD)
    if USE_TLS:
        c.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    c.reconnect_delay_set(min_delay=1, max_delay=60)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(HOST, PORT, keepalive=30)
    c.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
