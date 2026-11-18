"""Anomaly detection evaluation (target >= 90 % recall, low false alarms).  OWNER: Part 2

Ground truth: injected faults CSV (simulator FAULT_LOG, or anomaly/generate.py --faults-out).
Predictions, either:
  - replayed: the readings are run through the trained models with the same
    "CONSECUTIVE anomalous readings in a row" rule as the live detector (default), or
  - recorded: --alerts with the anomaly alerts from a live run (data/buffer_Alerts.jsonl
    when ADX is off, or an export of the Alerts table).

An alert "episode" runs from the moment an alert is sent until readings look
normal again. Anomalies the live detector holds off (settling after an incident) send no
alert and don't count for anything. A fault counts as
detected if an episode for that appliance overlaps the fault, from start_ts to
start_ts + ticks * 5 s + --grace seconds. This way two back-to-back faults covered
by one ongoing alert both count. An episode that overlaps no fault is a false alarm.
With --alerts (recorded alerts) only the alert time is known, so an episode is
just that moment.

Usage (repo root):
    python tests/eval_anomaly.py data/test.jsonl data/test_faults.csv
    python tests/eval_anomaly.py data/buffer_PowerRaw.jsonl data/injected_faults.csv \\
        --alerts data/buffer_Alerts.jsonl --markdown
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "processor"))
from anomaly.detector import CONSECUTIVE, HOLD_OFF, MODEL_DIR, load_models  # noqa: E402
from anomaly.features import features_from_frame  # noqa: E402

TICK = pd.to_timedelta(5, unit="s")


def replay_alerts(readings, models):
    """Alert episodes per appliance: same rules as the live detector, on batch predictions.
    An episode starts when an alert is SENT and lasts while the readings stay anomalous."""
    rows = []
    for appliance, g in readings.sort_values("ts").groupby("appliance"):
        model = models.get(appliance)
        if model is None:
            continue
        X = features_from_frame(g)
        anomalous, settling = model.predict(X), model.settling_only(X)
        streak, alerted, ep = 0, False, None
        for ts, bad, settling_only in zip(g["ts"], anomalous, settling):
            if not bad:
                streak, alerted = 0, False
                continue
            streak += 1
            if streak < CONSECUTIVE:
                continue
            if alerted:
                ep["end"] = ts
                continue
            if ep is not None and ts - ep["end"] <= HOLD_OFF and settling_only:
                continue                      # settling after last incident (same as live)
            alerted = True
            ep = {"ts": ts, "end": ts, "appliance": appliance}
            rows.append(ep)
    return pd.DataFrame(rows, columns=["ts", "end", "appliance"])


def evaluate(readings, faults, alerts, grace_s=60):
    grace = pd.to_timedelta(grace_s, unit="s")
    faults = faults.copy()
    faults["end_ts"] = faults["start_ts"] + faults["ticks"] * TICK + grace
    faults["detected"] = False
    alerts = alerts.copy()
    alerts["matched"] = False
    if "end" not in alerts:
        alerts["end"] = alerts["ts"]
    for i, f in faults.iterrows():
        hit = ((alerts["appliance"] == f["appliance"])
               & (alerts["ts"] <= f["end_ts"]) & (alerts["end"] >= f["start_ts"]))
        faults.loc[i, "detected"] = hit.any()
        alerts.loc[hit, "matched"] = True

    span = readings.groupby("appliance")["ts"].agg(lambda s: (s.max() - s.min()))
    out = []
    for a in sorted(readings["appliance"].unique()):
        fa = faults[faults["appliance"] == a]
        hours = span[a].total_seconds() / 3600
        false_alarms = int(((alerts["appliance"] == a) & ~alerts["matched"]).sum())
        row = {"appliance": a, "faults": len(fa), "detected": int(fa["detected"].sum()),
               "false_alarms": false_alarms, "hours": hours}
        if "visible_ticks" in fa:
            vis = fa[fa["visible_ticks"] > 0]
            row.update(visible=len(vis), visible_detected=int(vis["detected"].sum()))
        out.append(row)
    return pd.DataFrame(out), faults


def report(table, markdown=False):
    t = table.copy()
    total = t.sum(numeric_only=True)
    total["appliance"] = "TOTAL"
    total["hours"] = t["hours"].mean()          # hours of data, same for every appliance
    t = pd.concat([t, total.to_frame().T], ignore_index=True)
    num = [c for c in t.columns if c != "appliance"]
    t[num] = t[num].astype(float)                           # 0/0 -> NaN, shown as "-"
    t["recall"] = (t["detected"] / t["faults"]).map(lambda x: f"{x:.0%}" if x == x else "-")
    t["fa_per_hour"] = (t["false_alarms"] / t["hours"]).map(lambda x: f"{x:.3f}")
    for c in ["faults", "detected", "false_alarms"] + (["visible", "visible_detected"] if "visible" in t else []):
        t[c] = t[c].astype(int)
    cols = ["appliance", "faults", "detected", "recall", "false_alarms", "fa_per_hour"]
    if "visible" in t:
        t["recall_visible"] = (t["visible_detected"] / t["visible"]).map(
            lambda x: f"{x:.0%}" if x == x else "-")
        cols.insert(4, "recall_visible")
    t = t[cols]
    if markdown:
        print("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols))
        for _, r in t.iterrows():
            print("| " + " | ".join(str(r[c]) for c in cols) + " |")
    else:
        print(t.to_string(index=False))


def load(readings_path, faults_path, alerts_path=None, model_dir=MODEL_DIR):
    readings = pd.read_json(readings_path, lines=True)
    readings["ts"] = pd.to_datetime(readings["ts"], utc=True)
    faults = pd.read_csv(faults_path)
    faults["ticks"] = faults["ticks"].astype("int64")      # also when the file has no faults
    faults["start_ts"] = pd.to_datetime(faults["start_ts"], utc=True)
    if alerts_path:
        alerts = pd.read_json(alerts_path, lines=True)
        alerts = alerts[alerts["type"] == "anomaly"][["ts", "appliance"]]
        alerts["ts"] = pd.to_datetime(alerts["ts"], utc=True)
    else:
        alerts = replay_alerts(readings, load_models(model_dir))
    return readings, faults, alerts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate anomaly detection against injected faults")
    ap.add_argument("readings")
    ap.add_argument("faults")
    ap.add_argument("--alerts", help="recorded alerts JSONL instead of replaying the models")
    ap.add_argument("--models", default=MODEL_DIR)
    ap.add_argument("--grace", type=float, default=60, help="seconds after a fault still counted")
    ap.add_argument("--markdown", action="store_true", help="table for docs/test_results.md")
    a = ap.parse_args(argv)
    readings, faults, alerts = load(a.readings, a.faults, a.alerts, a.models)
    table, _ = evaluate(readings, faults, alerts, a.grace)
    report(table, a.markdown)
    return table


if __name__ == "__main__":
    main()
