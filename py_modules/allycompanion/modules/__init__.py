"""Feature modules in display order. Planned: audio (Ally DSP), controller and fixes (Ally Fix),
lighting, power and battery, news; see docs/roadmap.md."""
from __future__ import annotations

from typing import List, Type

from ..module import Module

MODULES: List[Type[Module]] = []
