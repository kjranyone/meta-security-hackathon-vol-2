"""Policy layer interface: each nation's brain returns structured Decisions."""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class DiplomaticAction(BaseModel):
    kind: str  # improve | sanction | alliance_offer | threaten | trade_pact
    target: str


class Decisions(BaseModel):
    budget: dict[str, float] = Field(
        default_factory=lambda: {"military": 0.2, "welfare": 0.3, "stockpile": 0.2, "subsidy": 0.3}
    )
    diplomacy: list[DiplomaticAction] = []
    military_posture: str = "neutral"  # defensive | neutral | aggressive
    rationing: bool = False
    propaganda: bool = False
    rationale: str = ""


class NationView(BaseModel):
    """What one nation can see when deciding (prompt-ready serialization)."""
    tick: int
    me: dict
    prices: dict[str, float]
    god_params: dict[str, float]
    relations: dict[str, dict]          # trust/alliance/war per other nation
    market_news: list[str] = []
    recent_events: list[str] = []


class Policy(Protocol):
    def decide(self, view: NationView) -> Decisions: ...
