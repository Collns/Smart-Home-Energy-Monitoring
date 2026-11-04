# Test Results

> Save as `docs/test_results.md`. Fill in as tests are run. Each test: what you did, the numbers, pass/fail.

## Summary

| Test | Target | Result | Pass? | Owner | Date |
|------|--------|--------|-------|-------|------|
| End-to-end latency | < 2 s | | | Issaq | |
| Broker restart | 0 lost readings at QoS 1 | | | Mashal | |
| Azure outage | 0 lost readings | | | Collins | |
| Anomaly detection | ≥ 90 % of injected faults, low false alarms | | | Collins | |
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

**Training data:** ___ days of simulated data (`SPEED=` ___), `contamination=` ___
**Test data:** `FAULT_RATE=` ___ for ___ hours → ___ injected faults (`data/injected_faults.csv`)

| Appliance | Faults injected | Detected | Recall | False alarms / hour |
|-----------|-----------------|----------|--------|---------------------|
| refrigerator | | | | |
| air_conditioner | | | | |
| … | | | | |
| **Total** | | | | |

**Notes / tuning tried:**

## 5. Alert timing

**Method:** force a threshold breach (e.g. AC fault) and measure time from the breach point to the alert on `home/alerts`.

| Run | Breach time | Alert received | Delay |
|-----|-------------|----------------|-------|
| 1 | | | |
| 2 | | | |
| 3 | | | |

**Notes:**
