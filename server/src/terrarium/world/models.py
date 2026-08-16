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
    stockpile_months: dict[str, float] = Field(default_factory=lambda: {"energy": 3.0, "food": 4.0, "chips": 2.0})


class NationState(BaseModel):
    id: str
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


class WorldSpec(BaseModel):
    name: str = "default"
    nations: list[NationSpec]
    chokepoints: list[Chokepoint] = []
    routes: list[TradeRoute] = []
    map_geojson: str = "world.geojson"   # viewer hint (web/<file>)


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
