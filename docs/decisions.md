# Design Decisions

> Save as `docs/decisions.md`. Add one entry whenever the team makes a choice someone might ask "why?" about. These feed straight into the report's design-discussion section.

Template:

```
## D-XX: Title
**Date:** · **Decided by:**
**Context:** what problem we had
**Decision:** what we chose
**Alternatives:** what else we considered and why not
**Consequences:** what this changes / costs
```

---

## D-01: Simulate devices instead of using hardware
**Date:** Oct 20, 2026 · **Decided by:** All
**Context:** Need six appliances with realistic, repeatable data.
**Decision:** Python simulator, one thread per appliance, with noise, packet loss, malformed messages and labelled fault injection.
**Alternatives:** Real smart plugs: cost, only a few appliances, no controlled faults.
**Consequences:** Faults are known (ground truth), so ML accuracy can be measured.

## D-02: MQTT with Mosquitto
**Date:** Oct 20, 2026 · **Decided by:** All
**Context:** Lightweight publish/subscribe protocol for constrained devices.
**Decision:** MQTT via Eclipse Mosquitto with TLS, ACLs and persistence.
**Alternatives:** HTTP polling: more overhead, no push. Azure IoT Hub: managed, but hides the broker concepts the course covers.
**Consequences:** We configure security and reliability ourselves.

## D-03: QoS 1 for readings, QoS 2 for alerts
**Date:** Oct 20, 2026 · **Decided by:** All
**Context:** Readings every 5 s; alerts are rare but important.
**Decision:** QoS 1 for readings (at least once; a duplicate reading is harmless). QoS 2 for alerts (exactly once; no duplicate notifications).
**Consequences:** Slight overhead on alerts; possible duplicate readings, which `seq` makes detectable.

## D-04: Switch storage from InfluxDB to Azure Data Explorer
**Date:** Nov 2026 · **Decided by:** All · **Instructor approval:** ☐
**Context:** Proposal named InfluxDB 2.x (local).
**Decision:** Azure Data Explorer with streaming ingestion, retention policies and materialized views; Grafana via the ADX data source.
**Alternatives:** InfluxDB local: simplest, original plan. InfluxDB hosted on an Azure VM: same code, but we would manage the VM.
**Consequences:** Queries in KQL instead of Flux; adds Entra ID auth to the security layer; needs internet; latency now includes a cloud round trip; added an Azure outage test and local disk buffer.

## D-05: Roll-ups as ADX materialized views
**Date:** · **Decided by:**
**Context:** Need 1-minute averages and hourly energy kept for a year.
**Decision:** `Power1m` and `EnergyHourly` materialized views instead of computing in Python.
**Consequences:** Less processor code; roll-ups stay correct even if the processor restarts.

## D-06: Isolation Forest for anomaly detection
**Date:** · **Decided by:** Collins
**Context:** Detect unusual appliance behaviour without labelled training data.
**Decision:** One Isolation Forest per appliance on features (power, 1-min rolling mean, rolling range, hour of day); alert after 6 consecutive anomalous readings (30 s).
**Alternatives:** Fixed thresholds only: miss subtle faults. Autoencoder / LSTM: more data and tuning than the timeline allows.
**Consequences:** Needs a "normal" training week (generated with `SPEED=120`); `contamination` and the consecutive count trade recall against false alarms.
