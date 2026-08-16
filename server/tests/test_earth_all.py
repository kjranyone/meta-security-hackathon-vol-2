import json
from pathlib import Path

from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world import earth_all
from terrarium.world.models import Commodity
from terrarium.world.presets import load_preset
from terrarium.world.worldgen import CONSUMPTION, _supply

GEOJSON = Path(__file__).resolve().parents[2] / "web" / "world.geojson"


def _ratios(spec):
    supply = {c: 0.0 for c in CONSUMPTION}
    for sp in spec.nations:
        for c, v in _supply(sp.resources).items():
            supply[c] += v
    demand = {k: v * len(spec.nations) for k, v in CONSUMPTION.items()}
    return {c: supply[c] / demand[c] for c in supply}


def test_earth_all_deterministic_and_big():
    a = earth_all.build_earth_all()
    b = load_preset("earth_all")
    assert len(a.nations) >= 170
    assert a.model_dump(mode="json") == b.model_dump(mode="json"), "generation must be deterministic"


def test_earth_all_balance_and_coverage():
    spec = earth_all.build_earth_all()
    for c, r in _ratios(spec).items():
        assert r >= 1.15, f"{c} supply ratio {r:.2f} below 1.15"
    geo = json.loads(GEOJSON.read_text(encoding="utf-8"))
    claimed = {g for sp in spec.nations for g in sp.geo_ids}
    missing = [f["properties"]["ADMIN"] for f in geo["features"]
               if f["properties"]["ADMIN"] and "Antarctica" not in f["properties"]["ADMIN"]
               and f["properties"]["ADMIN"] not in claimed]
    assert not missing, f"unclaimed countries: {missing[:5]}"
    ids = [sp.id for sp in spec.nations]
    assert len(ids) == len(set(ids)), "nation ids must be unique"
    for r in spec.routes:
        assert r.importer in ids and r.exporter in ids
        if r.commodity == Commodity.SPACE:
            assert not r.chokepoints, "orbit lanes bypass chokepoints"


def test_earth_all_engine_smoke():
    spec = load_preset("earth_all")
    pol = {ns.id: HeuristicPolicy() for ns in spec.nations}
    eng = Engine(spec, pol, seed=42, out_dir=None)
    eng.run(2, Scenario())
    assert len(eng.snapshots) == 2
    assert eng.snapshots[-1]["metrics"]["world_gdp"] > 0
