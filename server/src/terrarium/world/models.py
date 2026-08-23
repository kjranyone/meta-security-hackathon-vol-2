"""Core data models: nations on a real-world map, resources, events, god params.

Geography model:
- nations sit at a lon/lat centroid and may "claim" real countries by
  GeoJSON ADMIN name (geo_ids) for map rendering
- resources are national production units (no hex tiles)
- chokepoints are real straits/canals at lon/lat
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Commodity(str, Enum):
    ENERGY = "energy"
    FOOD = "food"
    CHIPS = "chips"
    MINERALS = "minerals"   # 地下資源: レアアース・レアメタル・リチウム
    SPACE = "space"         # 宇宙資源: 軌道スロット・衛星インフラ


class ResourceKind(str, Enum):
    OIL = "oil"
    GAS = "gas"
    GRAIN = "grain"
    FAB = "fab"          # semiconductor fabrication
    FINANCE = "finance"  # capital hub (gdp growth bonus, no commodity)
    MINERAL = "mineral"  # 地下鉱物 (rare earths / lithium / rare metals)
    ORBIT = "orbit"      # 宇宙インフラ (orbital slots / satellite capacity)


RESOURCE_TO_COMMODITY: dict[ResourceKind, Commodity] = {
    ResourceKind.OIL: Commodity.ENERGY,
    ResourceKind.GAS: Commodity.ENERGY,
    ResourceKind.GRAIN: Commodity.FOOD,
    ResourceKind.FAB: Commodity.CHIPS,
    ResourceKind.MINERAL: Commodity.MINERALS,
    ResourceKind.ORBIT: Commodity.SPACE,
}


class Chokepoint(BaseModel):
    name: str
    lon: float
    lat: float
    closed: bool = False
    closed_since: Optional[int] = None
    # 封鎖の実効化度 0-1: 航行中の船はまだ着く。輸送力は REROUTE_TAU で漸減する
    throttle: float = 0.0


class TradeRoute(BaseModel):
    importer: str
    exporter: str
    commodity: Commodity
    share: float            # fraction of importer demand covered
    chokepoints: list[str] = []


class NationSpec(BaseModel):
    id: str
    name: str
    persona: str = ""
    color: str = "#888888"
    centroid: tuple[float, float]          # (lon, lat) for map rendering
    geo_ids: list[str] = []                # GeoJSON ADMIN names this nation claims
    population_m: float = 50.0
    gdp_t: float = 1.0
    military: float = 50.0
    stability: float = 60.0
    approval: float = 50.0
    aggression: float = 0.3
    paranoia: float = 0.3
    resources: list[ResourceKind] = []
    debt_gdp: float = 60.0            # sovereign debt as % of GDP at t0
    population_growth: float = 0.008   # 年率人口成長
    education: float = 0.5             # 教育水準 0-1（研究吸収・安定に寄与）
    gini: float = 0.38                 # 所得不平等（安定・支持に影響）
    energy_renew: float = 0.10         # 再生エネルギー比率 0-1（CO2に反映）
    unemployment: float = 6.0          # 初期失業率 %（実データがある国はその値）
    # 自国通貨建て債務の割合 0-1（-1は engines が導出）。主要通貨国は
    # 強制破綻がほぼ不可能で、危機はインフレ（通貨発行）で吸収される
    local_debt_share: float = -1.0
    # --- 思想・ドクトリン（政策の異質性の源。安全保障シミュレーションの中核） ---
    # 数値は中立的な分析用の様式化であり、特定国の実政策への言明ではない
    doctrine_risk: float = 0.5         # 危機許容度: 高いほど閾値近くまで冒険する
    doctrine_militarism: float = 0.3   # 軍事偏重: リチャードソン軍拡反応・軍事報酬
    doctrine_revisionism: float = 0.2  # 修正主義: 現状変更志向が緊張を高める
    doctrine_vengeance: float = 0.3    # 報復性: 開戦後の疲弊耐性（執拗に戦い続ける）
    doctrine_treaty_fidelity: float = 0.7  # 同盟遵守度: 相互防衛の発動確率に効く
    nuclear_posture: str = "mad"       # counterforce | mad | nfu（先制安定性に効く）
    stockpile_months: dict[str, float] = Field(default_factory=lambda: {"energy": 3.0, "food": 4.0, "chips": 2.0})


class NationState(BaseModel):
    id: str
    # --- realism layer ---
    population_m: float = 50.0         # 人口（百万人）
    unemployment: float = 6.0          # 失業率 %
    fx: float = 1.0                    # 為替指数（初期1.0、下落=通貨安）
    fx_reserves: float = 8.0           # 外貨準備（輸入月数）
    ca_last: float = 0.0               # 直近tickの経常収支（フロー値）
    infra: float = 1.0                 # インフラ指数（生産力倍率）
    co2_cum: float = 0.0               # CO2累積排出（指数）
    renew_eff: float = 0.10            # 実効再生エネルギー比率
    # --- 非決定戦略因子（核 etc.）: 保有リストと取得進捗 ---
    factors: list[str] = []
    factor_progress: dict[str, float] = {}
    doctrines: dict[str, str] = {}     # factor_id -> pursue | hold | abandon
    name: str
    persona: str = ""
    color: str = "#888888"
    gdp: float                      # trillions
    gdp_growth: float = 0.02
    inflation: float = 0.02
    population_m: float
    military: float
    stability: float
    approval: float
    war_exhaustion: float = 0.0
    aggression: float
    paranoia: float
    stocks: dict[str, float]        # months of consumption per commodity
    base_aggression: float          # pre-god-override values (for reset)
    base_paranoia: float
    rationing: bool = False
    propaganda: bool = False
    budget: dict[str, float] = Field(default_factory=lambda: {"military": 0.2, "welfare": 0.3, "stockpile": 0.2, "subsidy": 0.3})
    trust: dict[str, float] = Field(default_factory=dict)
    alliances: list[str] = []
    sanctions_on: list[str] = []
    at_war_with: list[str] = []
    collapsed: bool = False
    collapse_ticks: int = 0
    debt_gdp: float = 60.0            # sovereign debt as % of GDP
    credibility: float = 80.0         # sovereign credit 0-100 (drives risk premium)
    defaults: int = 0                 # lifetime default count
    default_cooldown: int = 0         # post-default restructuring moratorium
    # 思想・ドクトリン（specからコピー。観測・RL・LLMから見える）
    doctrine_risk: float = 0.5
    doctrine_militarism: float = 0.3
    doctrine_revisionism: float = 0.2
    doctrine_vengeance: float = 0.3
    doctrine_treaty_fidelity: float = 0.7
    nuclear_posture: str = "mad"
    insurgency_cooldown: int = 0      # 内戦ハザードの冷却（tick）
    local_debt_share: float = 0.5     # 自国通貨建て債務割合（specから導出コピー）
    # 創発するイデオロギー圏（実在宗教の割付ではない。宗教系技術の採用で移行）
    ideology: str = "secular"         # secular | ai_cult | techno_nationalist

    def view(self) -> dict[str, Any]:
        return self.model_dump()


class GodParams(BaseModel):
    trade_efficiency: float = 1.0
    food_yield: float = 1.0
    energy_yield: float = 1.0
    chips_yield: float = 1.0
    minerals_yield: float = 1.0
    space_yield: float = 1.0
    ai_aggression: float = 1.0
    disinfo_intensity: float = 1.0
    world_rate_hike: float = 0.0      # god's rate hike added to every nation's rate
    fog_of_war: float = 0.0           # 情報の霧: 相手国の信頼推定を平均へ退行させる（誤認の源）


class WorldSpec(BaseModel):
    factor_holders: dict[str, list[str]] = Field(default_factory=dict)  # factor_id -> nation ids
    name: str = "default"
    nations: list[NationSpec]
    chokepoints: list[Chokepoint] = []
    routes: list[TradeRoute] = []
    map_geojson: str = "world.geojson"   # viewer hint (web/<file>)
    # ---- シミュレーション時計: 1tickの実時間（時間）。動力学は実時間で校正済み ----
    # 720 = 月次圧縮時計（実験・訓練・旧互換）。1 = 神モードのRTS時計。
    hours_per_tick: float = 720.0
    # 国家の意思決定周期（時間）。None = 毎tick。神モードでは週次(168)を推奨:
    # 政府は毎時間閣議を開かない。決定は次の決定点まで継続適用される。
    decision_every_hours: Optional[float] = None


class EventRecord(BaseModel):
    id: str
    tick: int
    type: str
    actor: Optional[str] = None
    targets: list[str] = []
    parents: list[str] = []
    data: dict[str, Any] = Field(default_factory=dict)
    text: str = ""


class TickSnapshot(BaseModel):
    tick: int
    nations: dict[str, dict[str, Any]]
    prices: dict[str, float]
    chokepoints: dict[str, bool]
    metrics: dict[str, float]
    events: list[str]      # event ids this tick
    news: list[str]
