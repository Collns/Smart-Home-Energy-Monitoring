# Test Results

> Save as `docs/test_results.md`. Fill in as tests are run. Each test: what you did, the numbers, pass/fail.

## Summary

| Test | Target | Result | Pass? | Owner | Date |
|------|--------|--------|-------|-------|------|
| End-to-end latency | < 2 s | | | Issaq | |
| Broker restart | 0 lost readings at QoS 1 | | | Mashal | |
| Azure outage | 0 lost readings | | | Collins | |
| Anomaly detection | ≥ 90 % of injected faults, low false alarms | 87 % live (98 % excl. water heater), 89–91 % offline, ≈ 2 false alarms / day | ⚠️ just below; water heater faults look like normal heating | Collins | Nov 18 |
| Alert timing | < 10 s after threshold breach | | | Collins | |

---

## 1. End-to-end latency

**Setup:** simulator → broker → processor → ADX (streaming ingestion). `ADX_FLUSH_S=` ___
**Method:** `ingestion_time() - ts` over ___ minutes (query in `tests/latency_test.py`).

| Metric | Value |
|--------|-------|
| p50 | |
| p95 | |
| max | |
| Readings measured | |

**Notes:**

## 2. Broker restart

**Setup:** `DROP_RATE=0`, `MALFORMED_RATE=0`, QoS 1, persistence on.
**Method:** `docker compose restart mosquitto` × ___ times over ___ minutes; count `seq` gaps per device.

| Device | Expected | Received | Missing |
|--------|----------|----------|---------|
| refrigerator | | | |
| microwave | | | |
| washing_machine | | | |
| water_heater | | | |
| air_conditioner | | | |
| television | | | |

**Notes:**

## 3. Azure outage

**Method:** block access to Azure (disconnect network or use a wrong cluster URI) for ___ minutes, then restore. Compare readings sent with rows in `PowerRaw`.

| Outage length | Readings during outage | Rows in ADX after recovery | Missing |
|---------------|------------------------|-----------------------------|---------|
| | | | |

**Notes:**

## 4. Anomaly detection

**Model:** one per appliance = Isolation Forest (200 trees, `contamination=0.001`) + learned envelope
(normal max of power / 1-min mean / ON duration / ON share of 30 min, normal min of rest between ON
periods, 10 % margin). Alert after 12 anomalous readings in a row (1 min). For 60 min after an alert,
anomalies with no sign of a new fault (no power / ON-duration feature above normal) are treated as the
appliance settling back into rhythm and don't alert. See `processor/anomaly/model.py`, `detector.py`.
**Training data:** 7 days of normal data from the simulator profiles (`anomaly/generate.py --days 7`, no faults)
**Method:** `python tests/eval_anomaly.py <readings> <faults>` replays the readings through the same rules as
the live detector. A fault counts as detected only if an alert is sent during it (+60 s grace) or an alert is
still active when it starts. Every other alert is a false alarm.

### 4a. Live pipeline run – Nov 18

**Setup:** simulator → Mosquitto (TLS, auth) → processor, `SPEED=60`, `FAULT_RATE=0.0005`, `DROP_RATE=0.01`,
`MALFORMED_RATE=0.005`, `ADX_ENABLED=false`, ~1.2 h real time = 78 h simulated, 313,622 readings, 156 injected faults.
Readings from the live run, replayed through the final detector (replay checked against the live detector's
own alerts: same alerts, at most 1–2 readings apart).

| Appliance | Faults injected | Detected | Recall | False alarms / hour |
|-----------|-----------------|----------|--------|---------------------|
| air_conditioner | 27 | 27 | 100% | 0.013 |
| microwave | 26 | 26 | 100% | 0.013 |
| refrigerator | 24 | 21 | 88% | 0.000 |
| television | 33 | 33 | 100% | 0.000 |
| washing_machine | 22 | 22 | 100% | 0.000 |
| water_heater | 24 | 6 | 25% | 0.063 |
| **Total** | **156** | **135** | **87%** | **0.089** (≈ 2 / day) |

Without the water heater: 129 / 132 = **98 %**.

### 4b. Offline evaluation (simulator profiles, no MQTT)

| Data | Faults | Recall | False alarms |
|------|--------|--------|--------------|
| 3 days, seed 2 | 137 | 89% | 1 (0.01 / h) |
| 7 days, seed 3 (unseen) | 333 | 91% | 13 (0.08 / h) |
| 7 days, seed 4 (unseen) | 303 | 91% | 15 (0.09 / h) |
| 7 normal days, no faults | 0 | – | 6 (0.04 / h, < 1 per day) |

**Result:** 87 % live / 89–91 % offline against the ≥ 90 % target. Every appliance except the water heater
is at 88–100 %. See notes for the water heater.

**Notes / tuning tried:**
- Baseline (skeleton features: power, 1-min mean/range, hour; `contamination=0.01`; 6 in a row):
  81 % recall, 2.1 false alarms / hour. Refrigerator 0 %.
- Lowering `contamination` cut false alarms but also recall (0.001 → 47 %). Reason: **Isolation Forest can't
  extrapolate** – its splits lie inside the training range, so an AC at 2400 W (normal max 1900 W) lands with the
  highest normal readings and scores as normal. Fix: the learned envelope.
- Fridge and water heater faults draw the same power as normal use and differ only in **timing**, so ON-duration
  and rest-before-ON features were added.
- False alarms right after real faults (cycle settling back into rhythm) → hold-off. A first version held off
  *all* anomalies for 30 min; the live run showed it also silenced new faults arriving soon after the previous
  one (11 of 33 TV faults missed live). It now only holds off anomalies with no sign of a new fault.
  Lesson: the first offline scoring counted those faults as caught; scoring is now strict (alert must be sent).
- **Water heater:** a heater "stuck on" for 5–20 min after a normal rest looks exactly like a normal heating
  cycle (normal: 10–20 min heating, any time of day), so it can't be told apart from normal use. Only faults
  that run longer than a normal cycle, or start too soon after one, are detectable. The 3 fridge misses happened
  while the compressor was already running normally, so the readings didn't change.
- Detection delay: about 1 min after the fault becomes visible (12 readings in a row).

## 5. Alert timing

**Method:** force a threshold breach (e.g. AC fault) and measure time from the breach point to the alert on `home/alerts`.

| Run | Breach time | Alert received | Delay |
|-----|-------------|----------------|-------|
| 1 | | | |
| 2 | | | |
| 3 | | | |

**Notes:**
