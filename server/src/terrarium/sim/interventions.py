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
    "create_resource",    # {nation: str, resource: str, quantity: int}  神が新たな資源を創る
    "grant_tech",         # {nation: str, tech: str}   神が技術を授ける
    "ban_tech",           # {tech: str}                神が技術を全世界で禁じる
    "bailout",            # {nation: str}              神が救済（債務削減・信用回復）
    "rate_hike",          # {value: float}             神が世界金利を引き上げる
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
