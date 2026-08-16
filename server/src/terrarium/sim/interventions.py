"""God interventions: cards and sliders, plus scenario files."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class Intervention(BaseModel):
    tick: int
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class Scenario(BaseModel):
    name: str = "baseline"
    description: str = ""
    interventions: list[Intervention] = []


GOD_CARD_TYPES = {
    "close_chokepoint",   # {chokepoint: str, duration: int|None}
    "open_chokepoint",    # {chokepoint: str}
    "destroy_resource",   # {nation: str, resource: str}
    "disaster",           # {nation: str, kind: drought|earthquake|epidemic}
    "disinfo",            # {target: str, origin: str|None, intensity: float}
    "set_param",          # {nation: str, param: aggression|paranoia, value: float}
    "global_slider",      # {param: trade_efficiency|food_yield|..., value: float}
}


def load_scenario(path: Optional[str]) -> Scenario:
    if not path:
        return Scenario()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Scenario(**data)
