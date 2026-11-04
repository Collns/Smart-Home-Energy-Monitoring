"""Anomaly detection evaluation (target >= 90 % recall, low false alarms).  OWNER: Part 2

Ground truth: data/injected_faults.csv (written by the simulator when FAULT_RATE > 0).
Predictions:  Alerts table where type == "anomaly".
A fault counts as detected if an anomaly alert for that appliance fires
between start_ts and start_ts + ticks * 5 s.
TODO Part 2: implement, report recall + false alarms per hour.
"""
