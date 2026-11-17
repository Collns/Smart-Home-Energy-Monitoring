"""Daily energy totals per appliance.  OWNER: Part 2

Daily kWh for the dashboard comes from ADX (EnergyHourly view + adx/queries/daily_energy.kql).
This is the processor's own running total, used to:
  - get daily totals when ADX is off (ADX_ENABLED=false, local mode)
  - cross-check the dashboard numbers for the report

Energy is power x time: each reading's watts are held until the next reading.
Days are UTC, the same as bin(ts, 1d) in ADX, so the two can be compared directly.
Finished days are appended to BUFFER_DIR/daily_energy.csv.
"""
import os
from datetime import timedelta

BUFFER_DIR = os.getenv("BUFFER_DIR", "/data")
# Don't count energy across a long gap (device offline): hold a reading for at most this long
MAX_HOLD = timedelta(seconds=60)


class DailyEnergy:
    def __init__(self, path=None):
        self.path = path or os.path.join(BUFFER_DIR, "daily_energy.csv")
        self.last = {}         # appliance -> (ts, power_w) of previous reading
        self.day = {}          # appliance -> date being totalled
        self.wh = {}           # appliance -> watt-hours so far that day

    def add(self, r):
        """Add one reading. Returns (day, appliance, kwh) when a day finishes, else None."""
        a, ts = r["appliance"], r["ts"]
        done = None
        if a in self.day and ts.date() > self.day[a]:
            done = (self.day[a], a, round(self.wh[a] / 1000, 3))
            self._save(*done)
            self.wh[a] = 0.0
        if a not in self.day or ts.date() > self.day[a]:
            self.day[a] = ts.date()
            self.wh.setdefault(a, 0.0)

        prev = self.last.get(a)
        if prev and ts > prev[0]:
            hold = min(ts - prev[0], MAX_HOLD)
            self.wh[a] += prev[1] * hold.total_seconds() / 3600
        if not prev or ts > prev[0]:
            self.last[a] = (ts, r["power_w"])
        return done

    def today(self):
        """Running kWh per appliance for the current day."""
        return {a: round(wh / 1000, 3) for a, wh in self.wh.items()}

    def _save(self, day, appliance, kwh):
        new = not os.path.exists(self.path)
        with open(self.path, "a") as f:
            if new:
                f.write("day,appliance,kwh\n")
            f.write(f"{day},{appliance},{kwh}\n")
        print(f"daily total {day} {appliance}: {kwh} kWh")
