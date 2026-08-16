"""Procedural world generation: seed -> balanced WorldSpec.

Design goals:
- deterministic: same (seed, params) -> identical world (bit-equal YAML dump)
- balanced: every commodity's world supply exceeds demand by >= margin,
  so a no-god baseline stays economically sane; scarcity is *created* by god
- plausible: 8 nation archetypes (resource autocracy, breadbasket, chip
  island, ...) with personas, non-overlapping territories, chokepoints on
  ocean seams between blocs, and import routes that make chokepoints matter
"""
from __future__ import annotations

import colorsys
import random
from typing import Optional

from pydantic import BaseModel, Field

from .hexgrid import hex_distance, neighbors, offset_to_axial
from .models import Chokepoint, Commodity, NationSpec, ResourceKind, Terrain, TradeRoute, WorldSpec

# consumption per nation per month, must mirror engine.CONSUMPTION
CONSUMPTION = {"energy": 1.0, "food": 1.0, "chips": 0.5}
YIELD_PER_HEX = 1.5           # mirrors engine production factor
SUPPLY_MARGIN = 1.15          # world supply >= demand * margin before routes


class GenParams(BaseModel):
    seed: int = 1
    cols: int = 26
    rows: int = 14
    n_nations: int = 8
    n_chokepoints: int = 4
    supply_margin: float = SUPPLY_MARGIN


class Archetype(BaseModel):
    key: str
    persona: str
    terrain: Terrain
    radius: int
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
              terrain=Terrain.DESERT, radius=3, resources=[ResourceKind.OIL, ResourceKind.OIL, ResourceKind.GAS],
              population_m=90, gdp_t=2.1, military=55, stability=50, approval=45, aggression=0.6, paranoia=0.5,
              stockpile={"energy": 8.0, "food": 2.0, "chips": 1.5}),
    Archetype(key="breadbasket", persona="穀物超大国。食料の輸出杠杆を外交の武器にする穏健な農業大国。",
              terrain=Terrain.PLAIN, radius=3, resources=[ResourceKind.GRAIN] * 4,
              population_m=200, gdp_t=3.4, military=45, stability=65, approval=60, aggression=0.25, paranoia=0.25,
              stockpile={"energy": 3.0, "food": 8.0, "chips": 2.0}),
    Archetype(key="chip_island", persona="技術立島国。半導体ファブを握るがエネルギーは海外依存。冷静な技術官僚主導。",
              terrain=Terrain.FOREST, radius=2, resources=[ResourceKind.FAB, ResourceKind.FAB],
              population_m=120, gdp_t=5.2, military=40, stability=72, approval=55, aggression=0.2, paranoia=0.35,
              stockpile={"energy": 2.0, "food": 3.0, "chips": 6.0}),
    Archetype(key="finance_hub", persona="金融ハブ都市国家。資本と情報が集まり、軍事力は小さいが経済杠杆は大きい。",
              terrain=Terrain.PLAIN, radius=2, resources=[ResourceKind.FINANCE, ResourceKind.FINANCE],
              population_m=60, gdp_t=4.0, military=25, stability=75, approval=60, aggression=0.15, paranoia=0.3,
              stockpile={"energy": 2.5, "food": 2.5, "chips": 3.0}),
    Archetype(key="industrial", persona="製造業大国。輸出依存の工業経済。エネルギーとチップを輸入し防衛的。",
              terrain=Terrain.PLAIN, radius=3, resources=[ResourceKind.FAB],
              population_m=150, gdp_t=4.8, military=50, stability=60, approval=50, aggression=0.4, paranoia=0.45,
              stockpile={"energy": 2.0, "food": 3.0, "chips": 3.0}),
    Archetype(key="emerging", persona="新興発展途上国。食料もエネルギーも輸入依存で、人口は若く大きい。不安定だが伸びる。",
              terrain=Terrain.DESERT, radius=2, resources=[],
              population_m=180, gdp_t=0.8, military=20, stability=45, approval=40, aggression=0.3, paranoia=0.4,
              stockpile={"energy": 1.5, "food": 1.5, "chips": 1.0}),
    Archetype(key="green_small", persona="高福祉の資源小国。再エネでほぼ自給。平和主義だが戦略的にも冷静。",
              terrain=Terrain.FOREST, radius=2, resources=[ResourceKind.GAS, ResourceKind.GRAIN],
              population_m=30, gdp_t=1.6, military=30, stability=80, approval=65, aggression=0.1, paranoia=0.2,
              stockpile={"energy": 6.0, "food": 2.0, "chips": 2.0}),
    Archetype(key="hegemon", persona="巨大な複合経済の覇権国。軍事力は最大級。穀物と石油を一部自給するが輸入も多い。",
              terrain=Terrain.PLAIN, radius=3, resources=[ResourceKind.OIL, ResourceKind.OIL, ResourceKind.GRAIN],
              population_m=300, gdp_t=6.5, military=80, stability=55, approval=50, aggression=0.5, paranoia=0.55,
              stockpile={"energy": 4.0, "food": 4.0, "chips": 2.0}),
]

# archetypes that can host extra hexes of each commodity when topping up
TOPUP_HOSTS = {
    "energy": {"oil_empire", "hegemon", "green_small"},
    "food": {"breadbasket", "hegemon", "green_small"},
    "chips": {"chip_island", "industrial"},
}

NAME_PREFIX = ["Vol", "Pet", "Gra", "Mer", "Kes", "Sah", "Nor", "Aur", "Zan", "Kar",
               "Lum", "Tar", "Bel", "Dor", "Vin", "Ost", "Umb", "Rav", "Cal", "Erm"]
NAME_SUFFIX = ["tania", "nova", "aria", "land", "ia", "mark", "stan", "burg",
               "heim", "dor", "gard", "pol", "rune", "via"]

CP_NAMES = ["Strait of {0}", "{0} Channel", "{0} Passage", "{0} Gate", "{0} Narrows",
            "Babel Channel", "Southern Gate", "Western Passage"]
CP_WORDS = ["Ormu", "Babel", "Sable", "Kite", "Mora", "Indra", "Tessa", "Vela"]


def _hsl_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _pick_archetypes(rng: random.Random, n: int) -> list[Archetype]:
    """Guarantee per-commodity exporter coverage, then fill with shuffled copies."""
    pool = list(ARCHETYPES)
    by_key = {a.key: a for a in pool}
    core = [by_key["oil_empire"], by_key["breadbasket"], by_key["chip_island"], by_key["hegemon"]]
    rest = [a for a in pool if a not in core]
    rng.shuffle(rest)
    order = core + rest
    if n <= len(order):
        return order[:max(4, n)]
    # more nations than archetypes: repeat shuffled copies (same archetype, different nation)
    picks = list(order)
    while len(picks) < n:
        extra = [a for a in order if a not in core] or order
        rng.shuffle(extra)
        picks.append(extra[len(picks) % len(extra)])
    return picks[:n]


def _place_centers(rng: random.Random, p: GenParams, arche: list[Archetype]) -> list[tuple[int, int]]:
    centers: list[tuple[int, int]] = []
    for a in arche:
        for _ in range(400):
            col = rng.randint(a.radius, p.cols - 1 - a.radius)
            row = rng.randint(a.radius, p.rows - 1 - a.radius)
            cq, cr = offset_to_axial(col, row)
            ok = all(hex_distance((cq, cr), offset_to_axial(*c)) >= a.radius + r + 1
                     for c, r in zip(centers, [x.radius for x in arche[:len(centers)]]))
            if ok:
                centers.append((col, row))
                break
        else:
            # fallback: scan grid deterministically for any legal spot
            found = False
            for row in range(p.rows):
                for col in range(p.cols):
                    cq, cr = offset_to_axial(col, row)
                    if all(hex_distance((cq, cr), offset_to_axial(*c)) >= a.radius + r + 1
                           for c, r in zip(centers, [x.radius for x in arche[:len(centers)]])):
                        centers.append((col, row))
                        found = True
                        break
                if found:
                    break
            if not found:
                centers.append((p.cols // 2, p.rows // 2))  # degenerate but never crash
    return centers


def _supply(resources: list[ResourceKind]) -> dict[str, float]:
    s = {"energy": 0.0, "food": 0.0, "chips": 0.0}
    for res in resources:
        if res is ResourceKind.FINANCE:
            continue
        c = {"oil": "energy", "gas": "energy", "grain": "food", "fab": "chips"}[res.value]
        s[c] += YIELD_PER_HEX
    return s


def _demand(n: int) -> dict[str, float]:
    return {k: v * n for k, v in CONSUMPTION.items()}


def _topup(rng: random.Random, p: GenParams, specs: list[NationSpec], arch: list[Archetype]) -> None:
    """Add resource hexes until every commodity clears supply >= demand * margin."""
    for _ in range(64):
        supply = {"energy": 0.0, "food": 0.0, "chips": 0.0}
        for sp in specs:
            for c, v in _supply(sp.resources).items():
                supply[c] += v
        demand = _demand(len(specs))
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


def _chokepoints(rng: random.Random, p: GenParams, specs: list[NationSpec]) -> list[Chokepoint]:
    """Ocean seams: ocean hexes touched by land of >=2 distinct owners."""
    land: dict[tuple[int, int], str] = {}
    for sp in specs:
        cq, cr = offset_to_axial(*sp.center)
        for col in range(p.cols):
            for row in range(p.rows):
                q, r = offset_to_axial(col, row)
                if hex_distance((q, r), (cq, cr)) <= sp.radius:
                    land[(q, r)] = sp.id
    seams: list[tuple[float, tuple[int, int]]] = []
    for col in range(p.cols):
        for row in range(p.rows):
            q, r = offset_to_axial(col, row)
            if (q, r) in land:
                continue
            owners = {land[n] for n in neighbors(q, r) if n in land}
            if len(owners) >= 2:
                seams.append((len(owners), (q, r)))
    seams.sort(key=lambda x: (-x[0], x[1]))
    picked: list[tuple[int, int]] = []
    for _, qr in seams:
        if len(picked) >= p.n_chokepoints:
            break
        if all(hex_distance(qr, o) >= 4 for o in picked):
            picked.append(qr)
    names: list[str] = []
    cp_words = list(CP_WORDS)
    rng.shuffle(cp_words)
    for i, (q, r) in enumerate(picked):
        tmpl = CP_NAMES[i % len(CP_NAMES)]
        word = cp_words[i % len(cp_words)]
        try:
            name = tmpl.format(word)
        except (IndexError, KeyError):
            name = f"{word} Strait"
        while name in names:
            name += " II"
        names.append(name)
    return [Chokepoint(name=n, q=q, r=r) for n, (q, r) in zip(names, picked)]


def _routes(rng: random.Random, p: GenParams, specs: list[NationSpec], cps: list[Chokepoint]) -> list[TradeRoute]:
    routes: list[TradeRoute] = []
    supply = {sp.id: _supply(sp.resources) for sp in specs}
    for c in CONSUMPTION:
        cons = CONSUMPTION[c]
        # exporter spare capacity (keep ~15% home margin like engine surplus logic)
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
            # 1-2 exporters cover the deficit; each route covers a share of *demand*
            remaining = deficit
            for rank, exp in enumerate(exporters[:2]):
                cover = min(remaining, spare[exp.id])
                if cover <= 0.05:
                    continue
                share = round(min(1.0, cover / cons), 2)
                remaining -= cover
                spare[exp.id] -= cover
                cp_names: list[str] = []
                if cps and rng.random() < 0.75:
                    mq = (offset_to_axial(*sp.center)[0] + offset_to_axial(*exp.center)[0]) / 2
                    mr = (offset_to_axial(*sp.center)[1] + offset_to_axial(*exp.center)[1]) / 2
                    nearest = min(cps, key=lambda cp: hex_distance((cp.q, cp.r), (mq, mr)))
                    cp_names = [nearest.name]
                commodity = Commodity(c)
                routes.append(TradeRoute(importer=sp.id, exporter=exp.id, commodity=commodity,
                                         share=share, chokepoints=cp_names))
                if remaining <= 0.05:
                    break
    return routes


def generate_world(params: Optional[GenParams] = None) -> WorldSpec:
    p = params or GenParams()
    # auto-grow the map when more than 8 nations won't fit the default 26x14
    if p.n_nations > 8:
        p.cols = max(p.cols, 26 + 4 * (p.n_nations - 8))
        p.rows = max(p.rows, 14 + ((p.n_nations - 8) + 1) // 2)
    rng = random.Random(f"worldgen:{p.seed}:{p.n_nations}:{p.cols}:{p.rows}:{p.n_chokepoints}")
    arch = _pick_archetypes(rng, p.n_nations)

    prefixes = rng.sample(NAME_PREFIX, min(len(NAME_PREFIX), p.n_nations))
    while len(prefixes) < p.n_nations:
        prefixes.append(rng.choice(NAME_PREFIX))
    suffixes = [rng.choice(NAME_SUFFIX) for _ in range(p.n_nations)]
    centers = _place_centers(rng, p, arch)

    specs: list[NationSpec] = []
    for i, a in enumerate(arch):
        j = lambda x: round(x * rng.uniform(0.9, 1.1), 2)  # small deterministic jitter
        specs.append(NationSpec(
            id=f"N{i:02d}",
            name=f"{prefixes[i]}{suffixes[i]}",
            persona=a.persona,
            color=_hsl_hex(i * 137.508 / 360.0, 0.55, 0.55),
            center=centers[i],
            radius=a.radius,
            population_m=j(a.population_m),
            gdp_t=j(a.gdp_t),
            military=j(a.military),
            stability=min(95.0, j(a.stability)),
            approval=min(95.0, j(a.approval)),
            aggression=round(max(0.05, min(0.9, rng.uniform(a.aggression - 0.05, a.aggression + 0.05))), 3),
            paranoia=round(max(0.05, min(0.9, rng.uniform(a.paranoia - 0.05, a.paranoia + 0.05))), 3),
            resources=list(a.resources),
            terrain_bias=a.terrain,
            stockpile_months={k: round(v * rng.uniform(0.85, 1.15), 1) for k, v in a.stockpile.items()},
        ))

    _topup(rng, p, specs, arch)
    cps = _chokepoints(rng, p, specs)
    routes = _routes(rng, p, specs, cps)

    return WorldSpec(
        name=f"gen_{p.seed}",
        cols=p.cols,
        rows=p.rows,
        nations=specs,
        chokepoints=cps,
        routes=routes,
    )
