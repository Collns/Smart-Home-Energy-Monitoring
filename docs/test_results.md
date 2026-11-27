# Test Results

> Save as `docs/test_results.md`. Fill in as tests are run. Each test: what you did, the numbers, pass/fail.

## Summary

| Test | Target | Result | Pass? | Owner | Date |
|------|--------|--------|-------|-------|------|
| End-to-end latency | < 2 s | p95 = 1.02 s | ✅ | Issaq | 2026-11-18 |
| Broker restart | 0 lost readings at QoS 1 | | | Mashal | |
| Azure outage | 0 lost readings | | | Collins | |
| Anomaly detection | ≥ 90 % of injected faults, low false alarms | 87 % live (98 % excl. water heater), 89–91 % offline, ≈ 2 false alarms / day | ⚠️ just below; water heater faults look like normal heating | Collins | Nov 18 |
| Alert timing | < 10 s after threshold breach | | | Collins | |

---

## 1. End-to-end latency

**Setup:** simulator → broker → processor → ADX (streaming ingestion). `ADX_FLUSH_S=` 1
**Method:** `ingestion_time() - ts` over 30 minutes (query run in the ADX web UI).

| Metric | Value |
|--------|-------|
| p50 | _to fill (Issaq)_ |
| p95 | 1.02 s |
| max | _to fill (Issaq)_ |
| Readings measured | _to fill (Issaq)_ |

**Query** (ADX web UI, database `SmartHomeEnergy`, over the 30-minute test window):

```kusto
PowerRaw
| where ts > ago(30m)
| extend latency_s = (ingestion_time() - ts) / 1s
| summarize p50 = percentile(latency_s, 50), p95 = percentile(latency_s, 95),
            max_s = max(latency_s), readings = count()
```

**Notes:**
- Result: p95 1.02 s against the < 2 s target → **PASS**, including the internet round trip to Azure.
- What the number covers: plug timestamp (`ts`) → Mosquitto (TLS) → processor (cleaning, alerts, ML) →
  1-s batch (`ADX_FLUSH_S=1`) → ADX streaming ingestion. Most of the delay is the 1-s batch plus the
  network call to Azure; the MQTT and processing steps take milliseconds (see the alert-timing test, §5).
- Not included: the Grafana refresh interval. The dashboard shows the latest value on its next refresh, so
  what a person sees can lag by up to one refresh interval on top of this.
- `ingestion_time()` is set by Azure's clock and `ts` by the simulator machine's clock, so a small clock
  difference between the two is part of the measurement.

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

**Method:** `python tests/alert_timing_test.py --runs 3 --markdown` (simulator stopped, monitor account set up).
The script acts as each appliance's plug and sends readings above its shortest threshold rule. Readings carry
timestamps 5 s apart but are sent quickly, so even the 1-h water-heater rule is reached in seconds. The clock
starts when the reading that completes the rule is sent and stops when the alert arrives on `home/alerts`:
plug → Mosquitto (TLS) → processor → Mosquitto → subscriber, all measured with one clock on the same machine.
Writing the alert to the ADX `Alerts` table happens in parallel (flushed every `ADX_FLUSH_S` = 1 s) and is not
part of this delay.

| Run | Appliance | Rule | Alert delay |
|---|---|---|---|
| 1 | air_conditioner | > 2000 W for 30 min | 0.009 s |
| 2 | air_conditioner | > 2000 W for 30 min | 0.050 s |
| 3 | air_conditioner | > 2000 W for 30 min | 0.009 s |
| 4 | refrigerator | > 100 W for 20 min | 0.052 s |
| 5 | refrigerator | > 100 W for 20 min | 0.012 s |
| 6 | refrigerator | > 100 W for 20 min | 0.009 s |
| 7 | microwave | > 900 W for 10 min | 0.053 s |
| 8 | microwave | > 900 W for 10 min | 0.009 s |
| 9 | microwave | > 900 W for 10 min | 0.014 s |
| 10 | washing_machine | > 1000 W for 5 min | 0.009 s |
| 11 | washing_machine | > 1000 W for 5 min | 0.010 s |
| 12 | washing_machine | > 1000 W for 5 min | 0.009 s |
| 13 | water_heater | > 4000 W for 1 h | 0.008 s |
| 14 | water_heater | > 4000 W for 1 h | 0.011 s |
| 15 | water_heater | > 4000 W for 1 h | 0.009 s |
| 16 | television | > 250 W for 5 min | 0.007 s |
| 17 | television | > 250 W for 5 min | 0.011 s |
| 18 | television | > 250 W for 5 min | 0.010 s |

**Summary:** p50 0.010 s · p95 0.053 s · max 0.053 s -> PASS (target < 10 s)
**Notes:** Development check (local Mosquitto without TLS, same ACLs, Nov 18): 12/12 alerts, max 0.03 s.
