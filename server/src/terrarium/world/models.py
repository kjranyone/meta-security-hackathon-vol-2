"""Core data models for the world, nations, events and god parameters."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Terrain(str, Enum):
    OCEAN = "ocean"
    PLAIN = "plain"
    MOUNTAIN = "mountain"
    DESERT = "desert"
    FOREST = "forest"


class Commodity(str, Enum):
    ENERGY = "energy"
    FOOD = "food"
    CHIPS = "chips"


class ResourceKind(str, Enum):
    OIL = "oil"
    GAS = "gas"
    GRAIN = "grain"
    FAB = "fab"          # semiconductor fabrication
    FINANCE = "finance"  # capital hub


RESOURCE_TO_COMMODITY: dict[ResourceKind, Commodity] = {
    ResourceKind.OIL: Commodity.ENERGY,
    ResourceKind.GAS: Commodity.ENERGY,
    ResourceKind.GRAIN: Commodity.FOOD,
    ResourceKind.FAB: Commodity.CHIPS,
    ResourceKind.FINANCE: Commodity.ENERGY,  # finance hubs contribute capital, modelled as small energy/gdp bonus
}


class HexTile(BaseModel):
    q: int
    r: int
    terrain: Terrain = Terrain.PLAIN
    owner: Optional[str] = None
    resource: Optional[ResourceKind] = None
    yield_mult: float = 1.0
    destroyed: bool = False


class Chokepoint(BaseModel):
    name: str
    q: int
    r: int
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
    center: tuple[int, int]          # offset (col,row)
    radius: int = 2
    population_m: float = 50.0
    gdp_t: float = 1.0
    military: float = 50.0
    stability: float = 60.0
    approval: float = 50.0
    aggression: float = 0.3
    paranoia: float = 0.3
    resources: list[ResourceKind] = []
    terrain_bias: Terrain = Terrain.PLAIN
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

    def view(self) -> dict[str, Any]:
        return self.model_dump()


class GodParams(BaseModel):
    trade_efficiency: float = 1.0
    food_yield: float = 1.0
    energy_yield: float = 1.0
    chips_yield: float = 1.0
    ai_aggression: float = 1.0
    disinfo_intensity: float = 1.0


class WorldSpec(BaseModel):
    name: str = "default"
    cols: int = 26
    rows: int = 14
    nations: list[NationSpec]
    chokepoints: list[Chokepoint] = []
    routes: list[TradeRoute] = []


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
