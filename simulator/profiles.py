"""Power profiles for each simulated appliance.  OWNER: Part 1

Each profile is a class with step(sim_time) -> watts.
`sim_time` is a datetime (simulated, may be fast-forwarded).
TODO Part 1: tune numbers so they look realistic; add more behaviour if needed.
"""
import math
import random
from datetime import datetime


class Profile:
    room = ""
    appliance = ""

    def __init__(self):
        self.fault = None          # name of an injected fault, or None
        self.fault_ticks_left = 0

    def base_power(self, t: datetime) -> float:
        raise NotImplementedError

    def step(self, t: datetime) -> float:
        watts = self.base_power(t)
        if self.fault:
            watts = self.apply_fault(watts)
            self.fault_ticks_left -= 1
            if self.fault_ticks_left <= 0:
                self.fault = None
        noise = random.gauss(0, max(1.0, watts * 0.02))   # ~2% sensor noise
        return max(0.0, watts + noise)

    # ---- fault injection (labelled faults for ML evaluation) ----
    def start_fault(self, ticks: int):
        self.fault = self.fault_name()
        self.fault_ticks_left = ticks

    def fault_name(self) -> str:
        return "spike"

    def apply_fault(self, watts: float) -> float:
        return watts * 2.5


class Refrigerator(Profile):
    room, appliance = "kitchen", "refrigerator"

    def __init__(self):
        super().__init__()
        self.on = False
        self.ticks_in_state = 0

    def base_power(self, t):
        # compressor: ~15 min on / ~25 min off at 5 s ticks
        self.ticks_in_state += 1
        limit = 180 if self.on else 300
        if self.ticks_in_state >= limit:
            self.on, self.ticks_in_state = not self.on, 0
        return 150.0 if self.on else 5.0

    def fault_name(self):
        return "compressor_stuck_on"

    def apply_fault(self, watts):
        return 150.0                 # runs nonstop


class Microwave(Profile):
    room, appliance = "kitchen", "microwave"

    def base_power(self, t):
        meal = t.hour in (7, 12, 18)
        if meal and random.random() < 0.08:
            return 1100.0
        return 2.0                   # standby clock


class WashingMachine(Profile):
    room, appliance = "laundry", "washing_machine"

    def __init__(self):
        super().__init__()
        self.cycle_tick = None

    def base_power(self, t):
        if self.cycle_tick is None and t.hour in (9, 19) and random.random() < 0.002:
            self.cycle_tick = 0
        if self.cycle_tick is None:
            return 1.0
        self.cycle_tick += 1
        if self.cycle_tick < 60:       # fill
            w = 100.0
        elif self.cycle_tick < 480:    # wash / heat
            w = 500.0
        elif self.cycle_tick < 600:    # spin
            w = 800.0
        else:
            self.cycle_tick = None
            w = 1.0
        return w


class WaterHeater(Profile):
    room, appliance = "utility", "water_heater"

    def base_power(self, t):
        busy = t.hour in (6, 7, 8, 19, 20, 21)
        if random.random() < (0.3 if busy else 0.03):
            return 4500.0
        return 0.0


class AirConditioner(Profile):
    room, appliance = "living_room", "air_conditioner"

    def base_power(self, t):
        # peaks mid-afternoon (sinusoid around 15:00)
        hour = t.hour + t.minute / 60
        load = max(0.0, math.cos((hour - 15) / 24 * 2 * math.pi))
        return 300.0 + 1700.0 * load ** 2

    def fault_name(self):
        return "overload"

    def apply_fault(self, watts):
        return 2400.0


class Television(Profile):
    room, appliance = "living_room", "television"

    def base_power(self, t):
        return 120.0 if 18 <= t.hour <= 23 else 0.5


ALL_PROFILES = [Refrigerator, Microwave, WashingMachine, WaterHeater, AirConditioner, Television]
