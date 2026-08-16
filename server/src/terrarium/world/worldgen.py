"""Procedural world generation: seed -> balanced fictional world ON the real map.

Fictional nations are placed at land points sampled from the vendored
Natural Earth GeoJSON, use the real straits/canals as chokepoints, and get
import routes wired through them. Supply/demand is auto-balanced like before.
"""
from __future__ import annotations

import colorsys
import json
import random
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .models import Chokepoint, Commodity, NationSpec, ResourceKind, TradeRoute, WorldSpec

# consumption per nation per month, mirrors engine.CONSUMPTION
CONSUMPTION = {"energy": 1.0, "food": 1.0, "chips": 0.5}
YIELD_PER_UNIT = 1.5         # mirrors engine production factor
SUPPLY_MARGIN = 1.15

WEB_DIR = Path(__file__).resolve().parents[3].parent / "web"
GEOJSON_PATH = WEB_DIR / "world.geojson"

# real chokepoints reused for generated worlds (subset with good spread)
REAL_CHOKEPOINTS = [
    ("Strait of Hormuz", 56.4, 26.6),
    ("Strait of Malacca", 101.5, 2.5),
    ("Taiwan Strait", 119.5, 24.5),
    ("Bab el-Mandeb", 43.4, 12.6),
    ("Suez Canal", 32.3, 30.2),
    ("Panama Canal", -79.7, 9.1),
    ("Turkish Straits", 29.1, 41.1),
    ("Strait of Gibraltar", -5.4, 35.9),
    ("Cape of Good Hope", 19.9, -34.8),
    ("Denmark Strait", -23.5, 66.5),
]


class GenParams(BaseModel):
    seed: int = 1
    n_nations: int = 8
    n_chokepoints: int = 6
    supply_margin: float = SUPPLY_MARGIN


class Archetype(BaseModel):
    key: str
    persona: str
    resources: list[ResourceKind]
    population_m: float
    gdp_t: float
    military: float
    stability: float
    approval: float
    aggression: float
    paranoia: float
    stockpile: dict[str, float] = Field(default_factory=dict)


ARCHETYPES: list[Archetype] = [
    Archetype(key="oil_empire", persona="資源専制国家。石油とガスの輸出で立ち、好戦的で疑い深い指導部。",
              resources=[ResourceKind.OIL, ResourceKind.OIL, ResourceKind.GAS],
              population_m=90, gdp_t=2.1, military=55, stability=50, approval=45, aggression=0.6, paranoia=0.5,
              stockpile={"energy": 8.0, "food": 2.0, "chips": 1.5}),
    Archetype(key="breadbasket", persona="穀物超大国。食料の輸出杠杆を外交の武器にする穏健な農業大国。",
              resources=[ResourceKind.GRAIN] * 4,
              population_m=200, gdp_t=3.4, military=45, stability=65, approval=60, aggression=0.25, paranoia=0.25,
              stockpile={"energy": 3.0, "food": 8.0, "chips": 2.0}),
    Archetype(key="chip_island", persona="技術立島国。半導体ファブを握るがエネルギーは海外依存。冷静な技術官僚主導。",
              resources=[ResourceKind.FAB, ResourceKind.FAB],
              population_m=120, gdp_t=5.2, military=40, stability=72, approval=55, aggression=0.2, paranoia=0.35,
              stockpile={"energy": 2.0, "food": 3.0, "chips": 6.0}),
    Archetype(key="finance_hub", persona="金融ハブ都市国家。資本と情報が集まり、軍事力は小さいが経済杠杆は大きい。",
              resources=[ResourceKind.FINANCE, ResourceKind.FINANCE],
              population_m=60, gdp_t=4.0, military=25, stability=75, approval=60, aggression=0.15, paranoia=0.3,
              stockpile={"energy": 2.5, "food": 2.5, "chips": 3.0}),
    Archetype(key="industrial", persona="製造業大国。輸出依存の工業経済。エネルギーとチップを輸入し防衛的。",
              resources=[ResourceKind.FAB],
              population_m=150, gdp_t=4.8, military=50, stability=60, approval=50, aggression=0.4, paranoia=0.45,
              stockpile={"energy": 2.0, "food": 3.0, "chips": 3.0}),
    Archetype(key="emerging", persona="新興発展途上国。食料もエネルギーも輸入依存で、人口は若く大きい。不安定だが伸びる。",
              resources=[],
              population_m=180, gdp_t=0.8, military=20, stability=45, approval=40, aggression=0.3, paranoia=0.4,
              stockpile={"energy": 1.5, "food": 1.5, "chips": 1.0}),
    Archetype(key="green_small", persona="高福祉の資源小国。再エネでほぼ自給。平和主義だが戦略的にも冷静。",
              resources=[ResourceKind.GAS, ResourceKind.GRAIN],
              population_m=30, gdp_t=1.6, military=30, stability=80, approval=65, aggression=0.1, paranoia=0.2,
              stockpile={"energy": 6.0, "food": 2.0, "chips": 2.0}),
    Archetype(key="hegemon", persona="巨大な複合経済の覇権国。軍事力は最大級。穀物と石油を一部自給するが輸入も多い。",
              resources=[ResourceKind.OIL, ResourceKind.OIL, ResourceKind.GRAIN],
              population_m=300, gdp_t=6.5, military=80, stability=55, approval=50, aggression=0.5, paranoia=0.55,
              stockpile={"energy": 4.0, "food": 4.0, "chips": 2.0}),
]

TOPUP_HOSTS = {
    "energy": {"oil_empire", "hegemon", "green_small"},
    "food": {"breadbasket", "hegemon", "green_small"},
    "chips": {"chip_island", "industrial"},
}

NAME_PREFIX = ["Vol", "Pet", "Gra", "Mer", "Kes", "Sah", "Nor", "Aur", "Zan", "Kar",
               "Lum", "Tar", "Bel", "Dor", "Vin", "Ost", "Umb", "Rav", "Cal", "Erm"]
NAME_SUFFIX = ["tania", "nova", "aria", "land", "ia", "mark", "stan", "burg",
               "heim", "dor", "gard", "pol", "rune", "via"]


def _hsl_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _pick_archetypes(rng: random.Random, n: int) -> list[Archetype]:
    by_key = {a.key: a for a in ARCHETYPES}
    core = [by_key["oil_empire"], by_key["breadbasket"], by_key["chip_island"], by_key["hegemon"]]
    rest = [a for a in ARCHETYPES if a not in core]
    rng.shuffle(rest)
    order = core + rest
    if n <= len(order):
        return order[:max(4, n)]
    picks = list(order)
    while len(picks) < n:
        extra = [a for a in order if a not in core] or order
        rng.shuffle(extra)
        picks.append(extra[len(picks) % len(extra)])
    return picks[:n]


def _load_land_polygons() -> list[list[tuple[float, float, float, float]]]:
    """Country polygons as flat [lon, lat] lists (outer rings only).
    Antarctica and far-southern islands are skipped."""
    data = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    polys = []
    for f in data["features"]:
        geom = f.get("geometry")
        if geom is None:
            continue
        rings = []
        if geom["type"] == "Polygon":
            rings = [geom["coordinates"][0]]
        elif geom["type"] == "MultiPolygon":
            rings = [poly[0] for poly in geom["coordinates"]]
        for ring in rings:
            ys = [p[1] for p in ring]
            if min(ys) < -59 or max(ys) > 84:   # Antarctica / far north fragments
                continue
            polys.append([(x, y) for x, y in ring])
    return polys


def _bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_poly(x: float, y: float, poly) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _sample_land_points(rng: random.Random, n: int, min_sep_deg: float = 22.0) -> list[tuple[float, float]]:
    polys = _load_land_polygons()
    weighted = []
    for p in polys:
        x0, y0, x1, y1 = _bbox(p)
        w = max(0.0, (x1 - x0) * (y1 - y0))
        if w > 0.5:  # skip tiny islands
            weighted.append((w, p))

    def dist(a, b):
        dx = min(abs(a[0] - b[0]), 360 - abs(a[0] - b[0]))
        return (dx ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    points: list[tuple[float, float]] = []
    for _ in range(n):
        for _ in range(600):
            total = sum(w for w, _ in weighted)
            pick = rng.random() * total
            poly = None
            for w, p in weighted:
                pick -= w
                if pick <= 0:
                    poly = p
                    break
            if poly is None:
                continue
            x0, y0, x1, y1 = _bbox(poly)
            x = rng.uniform(x0, x1)
            y = rng.uniform(y0, y1)
            if not _point_in_poly(x, y, poly):
                continue
            if all(dist((x, y), q) >= min_sep_deg for q in points):
                points.append((round(x, 1), round(y, 1)))
                break
        else:
            # relax separation until something fits
            for _ in range(2000):
                w, poly = weighted[rng.randrange(len(weighted))]
                x0, y0, x1, y1 = _bbox(poly)
                x = rng.uniform(x0, x1)
                y = rng.uniform(y0, y1)
                if _point_in_poly(x, y, poly):
                    points.append((round(x, 1), round(y, 1)))
                    break
            else:
                points.append((0.0, 0.0))
    return points


def _supply(resources: list[ResourceKind]) -> dict[str, float]:
    s = {"energy": 0.0, "food": 0.0, "chips": 0.0}
    for res in resources:
        if res is ResourceKind.FINANCE:
            continue
        s[RESOURCE_COMMO[res]] += YIELD_PER_UNIT
    return s


RESOURCE_COMMO = {"oil": "energy", "gas": "energy", "grain": "food", "fab": "chips"}


def _topup(rng: random.Random, p: GenParams, specs: list[NationSpec], arch: list[Archetype]) -> None:
    for _ in range(64):
        supply = {"energy": 0.0, "food": 0.0, "chips": 0.0}
        for sp in specs:
            for c, v in _supply(sp.resources).items():
                supply[c] += v
        demand = {k: v * len(specs) for k, v in CONSUMPTION.items()}
        deficits = {c: demand[c] * p.supply_margin - supply[c] for c in supply}
        worst = max(deficits, key=lambda c: deficits[c])
        if deficits[worst] <= 0:
            return
        res = {"energy": ResourceKind.OIL, "food": ResourceKind.GRAIN, "chips": ResourceKind.FAB}[worst]
        hosts = [i for i, a in enumerate(arch) if a.key in TOPUP_HOSTS[worst] and len(specs[i].resources) < 8]
        if not hosts:
            hosts = [i for i, sp in enumerate(specs) if len(sp.resources) < 8]
        if not hosts:
            return
        specs[rng.choice(hosts)].resources.append(res)


def _lon_dist(a: float, b: float) -> float:
    return min(abs(a - b), 360 - abs(a - b))


def _routes(rng: random.Random, p: GenParams, specs: list[NationSpec], cps: list[Chokepoint]) -> list[TradeRoute]:
    routes: list[TradeRoute] = []
    supply = {sp.id: _supply(sp.resources) for sp in specs}
    for c in CONSUMPTION:
        cons = CONSUMPTION[c]
        spare: dict[str, float] = {}
        for sp in specs:
            spare[sp.id] = max(0.0, supply[sp.id][c] - cons)
        for sp in specs:
            deficit = cons - supply[sp.id][c]
            if deficit <= 0.05:
                continue
            exporters = sorted(
                [o for o in specs if o.id != sp.id and spare.get(o.id, 0) > 0.05],
                key=lambda o: -spare[o.id],
            )
            if not exporters:
                continue
            remaining = deficit
            for exp in exporters[:2]:
                cover = min(remaining, spare[exp.id])
                if cover <= 0.05:
                    continue
                share = round(min(1.0, cover / cons), 2)
                remaining -= cover
                spare[exp.id] -= cover
                cp_names: list[str] = []
                if cps and rng.random() < 0.75:
                    # chokepoint near the corridor between the two countries
                    mid_lon = (sp.centroid[0] + exp.centroid[0]) / 2
                    mid_lat = (sp.centroid[1] + exp.centroid[1]) / 2
                    nearest = min(
                        cps,
                        key=lambda cp: _lon_dist(cp.lon, mid_lon) ** 2 + (cp.lat - mid_lat) ** 2,
                    )
                    cp_names = [nearest.name]
                routes.append(TradeRoute(importer=sp.id, exporter=exp.id, commodity=Commodity(c),
                                         share=share, chokepoints=cp_names))
                if remaining <= 0.05:
                    break
    return routes


def generate_world(params: Optional[GenParams] = None) -> WorldSpec:
    p = params or GenParams()
    rng = random.Random(f"worldgen:{p.seed}:{p.n_nations}:{p.n_chokepoints}")
    arch = _pick_archetypes(rng, p.n_nations)

    prefixes = rng.sample(NAME_PREFIX, min(len(NAME_PREFIX), p.n_nations))
    while len(prefixes) < p.n_nations:
        prefixes.append(rng.choice(NAME_PREFIX))
    suffixes = [rng.choice(NAME_SUFFIX) for _ in range(p.n_nations)]
    centroids = _sample_land_points(rng, p.n_nations)

    specs: list[NationSpec] = []
    for i, a in enumerate(arch):
        j = lambda x: round(x * rng.uniform(0.9, 1.1), 2)
        specs.append(NationSpec(
            id=f"N{i:02d}",
            name=f"{prefixes[i]}{suffixes[i]}",
            persona=a.persona,
            color=_hsl_hex(i * 137.508 / 360.0, 0.55, 0.55),
            centroid=centroids[i],
            geo_ids=[],
            population_m=j(a.population_m),
            gdp_t=j(a.gdp_t),
            military=j(a.military),
            stability=min(95.0, j(a.stability)),
            approval=min(95.0, j(a.approval)),
            aggression=round(max(0.05, min(0.9, rng.uniform(a.aggression - 0.05, a.aggression + 0.05))), 3),
            paranoia=round(max(0.05, min(0.9, rng.uniform(a.paranoia - 0.05, a.paranoia + 0.05))), 3),
            resources=list(a.resources),
            stockpile_months={k: round(v * rng.uniform(0.85, 1.15), 1) for k, v in a.stockpile.items()},
        ))

    _topup(rng, p, specs, arch)
    cps = [Chokepoint(name=n, lon=lon, lat=lat) for n, lon, lat in REAL_CHOKEPOINTS[:p.n_chokepoints]]
    routes = _routes(rng, p, specs, cps)

    return WorldSpec(
        name=f"gen_{p.seed}",
        nations=specs,
        chokepoints=cps,
        routes=routes,
    )
