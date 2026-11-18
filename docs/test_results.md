# Test Results

> Save as `docs/test_results.md`. Fill in as tests are run. Each test: what you did, the numbers, pass/fail.

## Summary

| Test | Target | Result | Pass? | Owner | Date |
|------|--------|--------|-------|-------|------|
| End-to-end latency | < 2 s | | | Issaq | |
| Broker restart | 0 lost readings at QoS 1 | | | Mashal | |
| Azure outage | 0 lost readings | | | Collins | |
| Anomaly detection | ≥ 90 % of injected faults, low false alarms | 91 % recall, < 1 false alarm / day (offline) | ✅ offline, live run to do | Collins | Nov 18 |
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
periods, 10 % margin). Alert after 12 anomalous readings in a row (1 min), then 30 min hold-off per
appliance. See `processor/anomaly/model.py`.
**Training data:** 7 days of normal data from the simulator profiles (`anomaly/generate.py --days 7`, no faults)
**Method:** `python tests/eval_anomaly.py <readings> <faults>`. A fault counts as detected if an alert episode
overlaps it (+60 s grace). Every other alert episode is a false alarm.

### 4a. Offline evaluation (simulator profiles, no MQTT) – Nov 18

Test data: `generate.py --days 3 --fault-rate 0.0005 --seed 2` → 137 injected faults (5–30 min each).

| Appliance | Faults injected | Detected | Recall | False alarms / hour |
|-----------|-----------------|----------|--------|---------------------|
| air_conditioner | 22 | 22 | 100% | 0.000 |
| microwave | 21 | 21 | 100% | 0.000 |
| refrigerator | 22 | 19 | 86% | 0.000 |
| television | 29 | 29 | 100% | 0.000 |
| washing_machine | 20 | 20 | 100% | 0.000 |
| water_heater | 23 | 13 | 57% | 0.000 |
| **Total** | **137** | **124** | **91%** | **0.000** |

Checked on data the model never saw:

| Data | Faults | Recall | False alarms |
|------|--------|--------|--------------|
| 7 days, seed 3 | 333 | 92% | 7 (0.04 / h) |
| 7 days, seed 4 | 303 | 92% | 12 (0.07 / h) |
| 7 normal days, no faults | 0 | – | 6 (0.04 / h, < 1 per day) |

**Result: PASS (≥ 90 %)** offline. Live pipeline run still to do (4b).

**Notes / tuning tried:**
- Baseline (skeleton features: power, 1-min mean/range, hour; `contamination=0.01`; 6 in a row):
  81 % recall, 2.1 false alarms / hour. Refrigerator 0 %.
- Lowering `contamination` cut false alarms but also recall (0.001 → 47 %). Reason: **Isolation Forest can't
  extrapolate** – its splits lie inside the training range, so an AC at 2400 W (normal max 1900 W) lands with the
  highest normal readings and scores as normal. Fix: the learned envelope.
- Fridge and water heater faults draw the same power as normal use and differ only in **timing**, so ON-duration
  and rest-before-ON features were added.
- Most remaining false alarms came 4–15 min *after* a real fault ended (the appliance's normal cycle restarts with
  a short rest) → 30 min hold-off per appliance.
- **Undetectable faults:** a water heater "stuck on" for 9–21 min after a normal rest looks exactly like a
  normal heating cycle (normal: 10–20 min). That's all of the water-heater misses. The 3 fridge misses happened
  while the compressor was already running normally, so the readings didn't change (recall on faults that
  changed the readings: 100 %).
- Detection delay: about 1 min after the fault becomes visible (12 readings in a row).

### 4b. Live pipeline run

**Setup:** simulator `FAULT_RATE=` ___ `SPEED=` ___ for ___ h → processor → `data/buffer_Alerts.jsonl`
**Method:** `python tests/eval_anomaly.py data/buffer_PowerRaw.jsonl data/injected_faults.csv --alerts data/buffer_Alerts.jsonl --markdown`

(paste table here)

## 5. Alert timing

**Method:** force a threshold breach (e.g. AC fault) and measure time from the breach point to the alert on `home/alerts`.

| Run | Breach time | Alert received | Delay |
|-----|-------------|----------------|-------|
| 1 | | | |
| 2 | | | |
| 3 | | | |

**Notes:**
