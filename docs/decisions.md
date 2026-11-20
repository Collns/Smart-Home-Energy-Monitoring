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
**Date:** Nov 16, 2026 · **Decided by:** Issaq
**Context:** Need 1-minute averages and hourly energy kept for a year.
**Decision:** `Power1m` and `EnergyHourly` materialized views instead of computing in Python. `EnergyHourly` stores the hour's average watts (`avg_w`) and reading count (`samples`); kWh is `avg_w / 1000` per hour, computed in the dashboard queries.
**Consequences:** Less processor code; roll-ups stay correct even if the processor restarts. Raw readings expire after 30 days while the views keep a year, and dashboards read the small views instead of scanning raw data. An hour that is still in progress counts as a full hour, so today's energy reads slightly high until each hour ends.

## D-06: Isolation Forest for anomaly detection
**Date:** · **Decided by:** Collins
**Context:** Detect unusual appliance behaviour without labelled training data.
**Decision:** One Isolation Forest per appliance on features (power, 1-min rolling mean, rolling range, hour of day); alert after 6 consecutive anomalous readings (30 s).
**Alternatives:** Fixed thresholds only: miss subtle faults. Autoencoder / LSTM: more data and tuning than the timeline allows.
**Consequences:** Needs a "normal" training week (generated with `SPEED=120`); `contamination` and the consecutive count trade recall against false alarms.

## D-07: Host ADX and the app registrations in a personal Azure tenant
**Date:** Nov 16, 2026 · **Decided by:** Issaq · **Instructor informed:** ☐
**Context:** The school (Ontario Tech) Microsoft account returns "You don't have access" (401) on Microsoft Entra ID, so students cannot create the `sp-processor` and `sp-grafana` app registrations. This blocked both Part 3 (ADX) and the Azure-security task in Part 1.
**Decision:** Created a personal Azure account (free sign-up, which creates its own Entra ID tenant). The free ADX cluster, database `SmartHomeEnergy` and both app registrations live there. Issaq did the app registrations, which were originally a Part 1 task.
**Alternatives:** Ask IT or the instructor to create app registrations in the school tenant: uncertain and slow. Use personal user logins instead of service principals: breaks the least-privilege design.
**Consequences:** The database depends on one member's personal account, so the course should be told. Credentials are shared privately with teammates, never through Git or group chat. The account has a card on file for identity verification only; no paid resources are created.

## D-08: Least-privilege access and secret rotation
**Date:** Nov 16, 2026 · **Decided by:** Issaq
**Context:** The processor and Grafana need non-interactive access to ADX.
**Decision:** Two service principals: `sp-processor` with the **Database Ingestor** role (write only) and `sp-grafana` with **Database Viewer** (read only), granted with `adx/04_security.kql`. Secrets live only in each member's `.env` (git-ignored).
**Consequences:** A leaked Grafana secret cannot change data, and a leaked processor secret cannot read it. To rotate a secret: create the new one, update `.env`, recreate the processor and Grafana containers (`docker compose up -d --force-recreate --no-deps <service>`, since containers only read `.env` when created), confirm data still flows, then delete the old secret. Permissions are tied to the client ID, so rotating a secret does not need `04_security.kql` re-run.

## D-09: Dashboard provisioned from a file with a fixed data source ID
**Date:** Nov 18, 2026 · **Decided by:** Issaq
**Context:** Each member runs their own Grafana, and a dashboard built in the UI is stored only in that member's Docker volume. Grafana also gives a provisioned data source a random ID unless one is set, so an exported dashboard breaks on other machines.
**Decision:** The data source has a fixed `uid: adx` (`grafana/provisioning/datasources/adx.yml`) and the dashboard is committed as `grafana/dashboards/energy.json`, which Grafana loads automatically. Every panel query is also kept in `adx/queries/`.
**Alternatives:** Share screenshots or rebuild by hand on each machine: not reproducible.
**Consequences:** Every member gets the same dashboard on `docker compose up`. A file-provisioned dashboard cannot be saved from the UI: edit it in Grafana, export the JSON and overwrite `energy.json`.

## D-10: Dashboard panel design
**Date:** Nov 18, 2026 · **Decided by:** Issaq
**Context:** Required panels: live gauges, stacked daily energy, peak-hour heatmap, Ontario TOU cost, alerts.
**Decision:**
- All queries use **Format as: Table**; the panel type decides the drawing.
- Daily energy and peak hours use **Toronto local time** (`datetime_utc_to_local`), so days and hours match the user's clock; ADX itself stores UTC.
- Daily energy is a **stacked bar chart** over a text day label (a pivoted table), because a time-series chart of daily bins showed nothing with only one or two days of data.
- The peak-hour "heatmap" is a **table with coloured cells**, each appliance coloured on its own scale to show its own busiest hours.
- Cost uses the **OEB time-of-use supply prices effective Nov 1, 2026** (off-peak $0.091, mid-peak $0.146, on-peak $0.189 per kWh), weekends off-peak. It excludes delivery, regulatory charges, HST and the rebate, so it is labelled an estimate. Statutory holidays are ignored because none falls in the project window.
- Layout runs from "now" (gauges, total energy, latency p95) to trend (power over time) to history (daily energy, peak hours) to action (cost, alerts).
**Consequences:** Rates must be updated each Nov 1 in `adx/queries/tou_cost.kql` and the dashboard.

## D-11: Mosquitto TLS port on Windows hosts
**Date:** Nov 17, 2026 · **Decided by:** Issaq
**Context:** On some Windows laptops, Docker cannot publish host port 8883 ("access permissions" error) because Windows (Hyper-V/WinNAT) reserves a port range that includes it. Mosquitto then fails to start and the simulator and processor wait forever.
**Decision:** The shared `docker-compose.yml` keeps `8883:8883`. A member who hits the error changes only the host side locally (e.g. `18883:8883`) and does not commit it. Containers still talk to each other on 8883, so nothing else changes.
**Alternatives:** `net stop winnat` / `net start winnat` as administrator, or a reboot: often frees the port, but the reservation can come back.
**Consequences:** Host tools such as `mosquitto_sub` must use the local port on that machine. Check reserved ranges with `netsh interface ipv4 show excludedportrange protocol=tcp`.
