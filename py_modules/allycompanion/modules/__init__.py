"""Feature modules in display order. The frontend groups them into pages (Audio: audio; Controller: vibration,
gyro, gamepad_layout; Power & battery: cpu_boost, fan, battery; Lighting: lighting)."""
from __future__ import annotations

from typing import List, Type

from ..module import Module
from .audio import Audio
from .battery import Battery
from .cpu_boost import CpuBoost
from .fan import Fan
from .gamepad_layout import GamepadLayout
from .gyro import Gyro
from .lighting import Lighting
from .vibration import Vibration

MODULES: List[Type[Module]] = [Audio, Vibration, Gyro, GamepadLayout, CpuBoost, Fan, Battery, Lighting]
