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
    doctrines: dict[str, str] = {}   # 因子 -> pursue | hold | abandon（戦略的自己選択）
    rationale: str = ""


class NationView(BaseModel):
    """What one nation can see when deciding (prompt-ready serialization).

    戦略推論の入力は「渡せるもの全部」: 現在値に加えて時系列トレンド・貿易構造
    （海峡曝露）・世界情勢・観測可能な他国概要・自分の直前の意思決定（記憶）・
    tick付きのイベント系列を含む。
    """
    tick: int
    me: dict
    prices: dict[str, float]
    god_params: dict[str, float]
    relations: dict[str, dict]          # trust/alliance/war per other nation
    market_news: list[str] = []
    recent_events: list[str] = []
    trends: dict = {}                   # 価格/自国指標の時系列モメンタム
    world: dict = {}                    # 世界情勢の要約とトレンド
    trade: dict = {}                    # 輸入依存・海峡曝露・輸出国構造
    last_decision: dict = {}            # 自分の直前の政策（無記憶AIへの記憶供給）


class Policy(Protocol):
    def decide(self, view: NationView) -> Decisions: ...
