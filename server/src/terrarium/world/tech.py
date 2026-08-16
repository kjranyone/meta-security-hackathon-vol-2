"""Emerging (paper-level) technologies and socio-religious movements.

Timeline: 1 tick = 1 month, run starts at "2026". unlock_tick marks when a
research-frontier concept matures from papers into a prototype that nations
can start absorbing. Effects are deliberately moderate so a no-god baseline
stays near equilibrium while adoption reshapes the balance of power.

Categories:
  weapon        兵器系 (military multipliers, deterrence friction)
  manufacturing 製造設備系 (commodity multipliers)
  resource      資源設備系 (new supply: flat output even without units)
  socio         宗教・社会運動系 (stability/approval/trust shifts)
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TechSpec(BaseModel):
    id: str
    name: str
    category: str                       # weapon | manufacturing | resource | socio
    unlock_tick: int
    desc: str = ""
    mult: dict[str, float] = Field(default_factory=dict)   # commodity production multipliers
    flat: dict[str, float] = Field(default_factory=dict)   # commodity supply added unconditionally
    military_mult: float = 1.0
    stability_drift: float = 0.0        # per tick while adopted
    approval_drift: float = 0.0         # per tick while adopted
    aggression_shot: float = 0.0        # one-shot on adoption
    paranoia_shot: float = 0.0          # one-shot on adoption
    trust_hit: float = 0.0              # other nations' trust toward adopter, one-shot


CATALOG: list[TechSpec] = [
    # ---------------------------------------------------------- weapons
    TechSpec(id="drone_swarm", name="自律ドローン群", category="weapon", unlock_tick=8,
             desc="群制御論文から生まれた自律 swarm。安価な打撃力が兵站を変える。",
             military_mult=1.25, stability_drift=-0.10),
    TechSpec(id="laser_defense", name="高出力レーザー迎撃", category="weapon", unlock_tick=14,
             desc="艦載指向エネルギー兵器が実用域に。ミサイル防衛のコスト構造が崩れる。",
             military_mult=1.15, approval_drift=0.20),
    TechSpec(id="cyber_arsenal", name="サイバー攻撃基盤", category="weapon", unlock_tick=5,
             desc="LLM生成の攻撃ツール群。平時の抑止が不信の抑止に置き換わる。",
             military_mult=1.10, aggression_shot=0.03, trust_hit=8.0),
    TechSpec(id="hypersonic_intercept", name="極超音速迎撃網", category="weapon", unlock_tick=22,
             desc="極超音速弾道の迎撃アルゴリズムが論文から射程へ。",
             military_mult=1.20),

    # -------------------------------------------------- manufacturing
    TechSpec(id="ai_fab", name="AI設計ファブ", category="manufacturing", unlock_tick=10,
             desc="生成AIがレイアウトを設計する次世代ファブ。歩上が構造的に上がる。",
             mult={"chips": 1.4, "minerals": 1.1}),
    TechSpec(id="biomanuf", name="バイオ製造プラント", category="manufacturing", unlock_tick=16,
             desc="発酵タンクでタンパク質と素材を作る。農地前提の食料地政学が揺れる。",
             mult={"food": 1.3}),
    TechSpec(id="autofactory", name="自己修復自動工場", category="manufacturing", unlock_tick=26,
             desc="自己診断・自己修理する無人工場クラスタ。製造の制約が外れる。",
             mult={"chips": 1.1, "minerals": 1.1, "energy": 1.1, "food": 1.1}),

    # ------------------------------------------------------ resources
    TechSpec(id="deepsea_mining", name="深海底鉱業", category="resource", unlock_tick=12,
             desc="レアメタル泥の採掘が商業化の閾値を超える。",
             mult={"minerals": 1.3}),
    TechSpec(id="fusion", name="核融合発電", category="resource", unlock_tick=20,
             desc="Q値を超えた炉がネットワークに接続される。エネルギー地政学の土台が動く。",
             flat={"energy": 1.2}),
    TechSpec(id="space_solar", name="宇宙太陽光発電", category="resource", unlock_tick=24,
             desc="軌道上で発電してマイクロ波で落とす。軌道スロットの価値が跳ねる。",
             flat={"energy": 0.8}, mult={"space": 1.2}),
    TechSpec(id="asteroid_mining", name="小惑星採掘", category="resource", unlock_tick=30,
             desc="レアアース小惑星の採掘ミッションが利益を返し始める。",
             flat={"minerals": 0.8}, mult={"space": 1.3}),

    # ---------------------------------------------------- socio / religion
    TechSpec(id="ai_religion", name="AI神格宗教の広がり", category="socio", unlock_tick=15,
             desc="LLMを神格とする新宗教が越境して普及。内部結束と外部への疑念が同時に伸びる。",
             stability_drift=0.30, approval_drift=0.30, paranoia_shot=0.04, trust_hit=6.0),
    TechSpec(id="techno_nationalism", name="テクノ・ナショナリズム", category="socio", unlock_tick=18,
             desc="技術主権を国民意識の中核に据える思潮。世論は沸くが外部とは擦れる。",
             approval_drift=0.40, military_mult=1.10, aggression_shot=0.04, trust_hit=5.0),
]


def tech_catalog_index() -> dict[str, TechSpec]:
    return {t.id: t for t in CATALOG}
