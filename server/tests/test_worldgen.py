import json

from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world.worldgen import CONSUMPTION, YIELD_PER_UNIT, GenParams, generate_world

REAL_CP_NAMES = {"Strait of Hormuz", "Strait of Malacca", "Taiwan Strait", "Bab el-Mandeb",
                 "Suez Canal", "Panama Canal", "Turkish Straits", "Strait of Gibraltar",
                 "Cape of Good Hope", "Denmark Strait"}


def test_generation_deterministic():
    a = generate_world(GenParams(seed=7)).model_dump()
    b = generate_world(GenParams(seed=7)).model_dump()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_supply_demand_balance_many_seeds():
    for seed in range(1, 9):
        spec = generate_world(GenParams(seed=seed))
        supply = {"energy": 0.0, "food": 0.0, "chips": 0.0}
        for n in spec.nations:
            for res in n.resources:
                if res.value == "finance":
                    continue
                c = {"oil": "energy", "gas": "energy", "grain": "food", "fab": "chips"}[res.value]
                supply[c] += YIELD_PER_UNIT
        demand = {k: v * len(spec.nations) for k, v in CONSUMPTION.items()}
        for c in demand:
            assert supply[c] >= demand[c] * 1.1, f"seed={seed} {c}: {supply[c]} < {demand[c] * 1.1}"


def test_centroids_on_land_and_spread():
    for seed in (3, 5, 11):
        spec = generate_world(GenParams(seed=seed))
        assert len({n.centroid for n in spec.nations}) == len(spec.nations), "duplicate centroids"
        for n in spec.nations:
            lon, lat = n.centroid
            assert -180 <= lon <= 180 and -60 <= lat <= 80, f"odd centroid {n.id}: {n.centroid}"


def test_real_chokepoints_used_and_routes_reference_them():
    for seed in (9, 12):
        spec = generate_world(GenParams(seed=seed))
        assert {cp.name for cp in spec.chokepoints} <= REAL_CP_NAMES
        cp_names = {cp.name for cp in spec.chokepoints}
        routed = [r for r in spec.routes if r.chokepoints]
        assert routed, "generated world should have chokepoint-exposed routes"
        assert all(set(r.chokepoints) <= cp_names for r in routed)


def test_generated_world_baseline_sanity():
    """No god, heuristic bots: prices must not blow up and nobody collapses early."""
    for seed in (2, 7):
        spec = generate_world(GenParams(seed=seed))
        eng = Engine(spec, {n.id: HeuristicPolicy() for n in spec.nations}, seed=1, out_dir=None)
        eng.run(24, Scenario())
        assert all(p <= 2.5 for p in eng.prices.values()), f"seed={seed} prices {eng.prices}"
        assert not any(n.collapsed for n in eng.nations.values()), f"seed={seed} collapsed nations"


def test_every_deficit_is_covered_by_routes():
    """Each importer with domestic deficit has at least one route per deficit commodity."""
    for seed in (4, 8):
        spec = generate_world(GenParams(seed=seed))
        routes_by = {}
        for r in spec.routes:
            routes_by.setdefault((r.importer, r.commodity.value), 0.0)
            routes_by[(r.importer, r.commodity.value)] += r.share
        for n in spec.nations:
            dom = {"energy": 0.0, "food": 0.0, "chips": 0.0}
            for res in n.resources:
                if res.value == "finance":
                    continue
                c = {"oil": "energy", "gas": "energy", "grain": "food", "fab": "chips"}[res.value]
                dom[c] += YIELD_PER_UNIT
            for c, cons in CONSUMPTION.items():
                deficit = cons - dom[c]
                covered = routes_by.get((n.id, c), 0.0) * cons
                if deficit > 0.15:
                    assert covered >= deficit * 0.7, (
                        f"seed={seed} {n.id} {c}: deficit {deficit:.2f} covered {covered:.2f}")
