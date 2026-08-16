import json

from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world.presets import load_preset


def _engine(seed: int = 7) -> Engine:
    spec = load_preset("default")
    policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
    return Engine(spec, policies, seed=seed, out_dir=None)


def test_same_seed_same_run():
    a, b = _engine(7), _engine(7)
    a.run(10, Scenario())
    b.run(10, Scenario())
    assert json.dumps(a.snapshots[-1], sort_keys=True) == json.dumps(b.snapshots[-1], sort_keys=True)
    assert [e.text for e in a.event_log.records] == [e.text for e in b.event_log.records]


def test_map_generation_deterministic_and_placed():
    eng = _engine()
    owned = [t for t in eng.tiles.values() if t.owner]
    assert len(owned) > 30  # 8 nations with radius 2-3
    # all chokepoints end up on ocean
    for cp in eng.chokepoints.values():
        assert eng.tiles[(cp.q, cp.r)].terrain.value == "ocean"


def test_chokepoint_closure_shocks_energy_importers():
    base, treat = _engine(11), _engine(11)
    scenario = Scenario(
        name="cp",
        interventions=[
            {"tick": 2, "type": "close_chokepoint", "params": {"chokepoint": "Strait of Ormuz", "duration": 20}}
        ],
    )
    base.run(14, Scenario())
    treat.run(14, scenario)
    # importers of Ormuz-routed energy should end with less energy stock than baseline
    for nid in ("KES", "VLT"):
        b = base.nations[nid].stocks["energy"]
        t = treat.nations[nid].stocks["energy"]
        assert t <= b, f"{nid}: treatment {t} should be <= baseline {b}"
    assert treat.prices["energy"] > base.prices["energy"]


def test_disinfo_drops_trust_and_raises_paranoia():
    eng = _engine(5)
    scenario = Scenario(
        name="disinfo",
        interventions=[{"tick": 3, "type": "disinfo", "params": {"target": "VLT", "intensity": 2.0}}],
    )
    eng.run(6, scenario)
    others = [n for k, n in eng.nations.items() if k != "VLT"]
    assert all(n.trust["VLT"] < 20.0 for n in others)
    assert eng.nations["VLT"].paranoia > eng.nations["VLT"].base_paranoia
    types = {r.type for r in eng.event_log.records}
    assert "disinfo" in types
