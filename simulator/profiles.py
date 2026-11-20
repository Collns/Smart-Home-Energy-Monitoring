"""Realistic power profiles for six simulated smart plugs. OWNER: Part 1.

Every profile exposes step(sim_time) -> power in watts.
The simulator calls step() once every five simulated seconds.
"""

import math
import random
from datetime import datetime


TICKS_PER_MINUTE = 12  # One reading every five simulated seconds.


class Profile:
    room = ""
    appliance = ""

    def __init__(self):
        self.fault = None
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
                self.fault_ticks_left = 0

        # Include approximately 2% measurement noise.
        noise = random.gauss(0.0, max(1.0, watts * 0.02))
        return max(0.0, watts + noise)

    def start_fault(self, ticks: int):
        if ticks <= 0:
            raise ValueError("Fault duration must be positive")
        self.fault = self.fault_name()
        self.fault_ticks_left = ticks

    def fault_name(self) -> str:
        return "power_spike"

    def apply_fault(self, watts: float) -> float:
        return watts * 2.5


class Refrigerator(Profile):
    room, appliance = "kitchen", "refrigerator"

    def __init__(self):
        super().__init__()
        self.compressor_on = True
        self.ticks_in_state = 0

    def base_power(self, t: datetime) -> float:
        # Compressor runs for 15 minutes, then rests for 25 minutes.
        self.ticks_in_state += 1
        limit = 15 * TICKS_PER_MINUTE if self.compressor_on else 25 * TICKS_PER_MINUTE
        if self.ticks_in_state >= limit:
            self.compressor_on = not self.compressor_on
            self.ticks_in_state = 0
        return 150.0 if self.compressor_on else 5.0

    def fault_name(self) -> str:
        return "compressor_stuck_on"

    def apply_fault(self, watts: float) -> float:
        return 150.0


class Microwave(Profile):
    room, appliance = "kitchen", "microwave"

    def __init__(self):
        super().__init__()
        self.cooking_ticks_left = 0
        self.cooldown_ticks_left = 0

    def base_power(self, t: datetime) -> float:
        # Once cooking starts, power stays high for one to four minutes.
        if self.cooking_ticks_left > 0:
            self.cooking_ticks_left -= 1
            return 1100.0

        if self.cooldown_ticks_left > 0:
            self.cooldown_ticks_left -= 1
            return 2.0

        if t.hour in (7, 12, 18, 19) and random.random() < 0.003:
            self.cooking_ticks_left = random.randint(1, 4) * TICKS_PER_MINUTE - 1
            self.cooldown_ticks_left = 15 * TICKS_PER_MINUTE
            return 1100.0

        return 2.0  # Clock / standby.

    def fault_name(self) -> str:
        return "unexpected_continuous_draw"

    def apply_fault(self, watts: float) -> float:
        return 1500.0


class WashingMachine(Profile):
    room, appliance = "laundry", "washing_machine"

    def __init__(self):
        super().__init__()
        self.cycle_tick = None

    def base_power(self, t: datetime) -> float:
        # Start a 50-minute cycle during typical laundry hours.
        if self.cycle_tick is None:
            if t.hour in (9, 19) and random.random() < 0.002:
                self.cycle_tick = 0
            else:
                return 1.0

        self.cycle_tick += 1
        if self.cycle_tick < 60:            # Fill (~5 min)
            return 100.0
        if self.cycle_tick < 480:           # Wash / heat (~35 min)
            return 500.0
        if self.cycle_tick < 600:           # Spin (~10 min)
            return 800.0

        self.cycle_tick = None
        return 1.0

    def fault_name(self) -> str:
        return "motor_overload"

    def apply_fault(self, watts: float) -> float:
        return max(watts, 1200.0)


class WaterHeater(Profile):
    room, appliance = "utility", "water_heater"

    def __init__(self):
        super().__init__()
        self.heating_ticks_left = 0
        self.cooldown_ticks_left = 0

    def base_power(self, t: datetime) -> float:
        # Heating happens in sustained cycles, not isolated five-second spikes.
        if self.heating_ticks_left > 0:
            self.heating_ticks_left -= 1
            return 4500.0

        if self.cooldown_ticks_left > 0:
            self.cooldown_ticks_left -= 1
            return 0.0

        busy = t.hour in (6, 7, 8, 19, 20, 21)
        start_probability = 0.004 if busy else 0.0004
        if random.random() < start_probability:
            self.heating_ticks_left = random.randint(10, 20) * TICKS_PER_MINUTE - 1
            self.cooldown_ticks_left = 25 * TICKS_PER_MINUTE
            return 4500.0

        return 0.0

    def fault_name(self) -> str:
        return "heater_stuck_on"

    def apply_fault(self, watts: float) -> float:
        return 4500.0


class AirConditioner(Profile):
    room, appliance = "living_room", "air_conditioner"

    def base_power(self, t: datetime) -> float:
        hour = t.hour + t.minute / 60.0
        if not 10 <= hour < 22:
            return 2.0  # Standby overnight.

        # A short compressor rest each hour; strongest load near 3 p.m.
        if t.minute >= 50:
            return 2.0
        afternoon_load = max(0.0, math.cos((hour - 15.0) * math.pi / 12.0))
        return 400.0 + 1500.0 * afternoon_load**2

    def fault_name(self) -> str:
        return "overload"

    def apply_fault(self, watts: float) -> float:
        return 2400.0


class Television(Profile):
    room, appliance = "living_room", "television"

    def base_power(self, t: datetime) -> float:
        evening = 18 <= t.hour < 23
        weekend_afternoon = t.weekday() >= 5 and 13 <= t.hour < 17
        return 120.0 if evening or weekend_afternoon else 0.5

    def fault_name(self) -> str:
        return "excess_power"

    def apply_fault(self, watts: float) -> float:
        return 450.0


ALL_PROFILES = [
    Refrigerator,
    Microwave,
    WashingMachine,
    WaterHeater,
    AirConditioner,
    Television,
]
