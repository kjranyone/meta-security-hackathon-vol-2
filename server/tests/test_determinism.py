import json

from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world.presets import load_preset


def _engine(seed: int = 7, preset: str = "default") -> Engine:
    spec = load_preset(preset)
    policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
    return Engine(spec, policies, seed=seed, out_dir=None)


def test_same_seed_same_run():
    a, b = _engine(7), _engine(7)
    a.run(10, Scenario())
    b.run(10, Scenario())
    assert json.dumps(a.snapshots[-1], sort_keys=True) == json.dumps(b.snapshots[-1], sort_keys=True)
    assert [e.text for e in a.event_log.records] == [e.text for e in b.event_log.records]


def test_earth_preset_loads_with_real_geography():
    eng = _engine(1, preset="earth")
    assert len(eng.nations) >= 14
    # real chokepoints present with coordinates
    for name in ("Strait of Hormuz", "Taiwan Strait", "Suez Canal"):
        assert name in eng.chokepoints
    spec = eng.spec
    assert any(spec_map := n.geo_ids for n in spec.nations), "earth nations should claim geo_ids"
    # every geo route references existing chokepoints
    cp_names = set(eng.chokepoints)
    assert all(set(r.chokepoints) <= cp_names for r in spec.routes)


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


def test_earth_hormuz_closure_shocks_asia_energy():
    """Real-world sanity: closing Hormuz must hurt East Asian importers."""
    def build():
        spec = load_preset("earth")
        return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations}, seed=3, out_dir=None)

    base, treat = build(), build()
    scenario = Scenario(
        name="hormuz",
        interventions=[{"tick": 2, "type": "close_chokepoint", "params": {"chokepoint": "Strait of Hormuz", "duration": 20}}],
    )
    base.run(14, Scenario())
    treat.run(14, scenario)
    for nid in ("JPN", "KOR", "CHN"):
        assert treat.nations[nid].stocks["energy"] <= base.nations[nid].stocks["energy"]
    assert treat.prices["energy"] > base.prices["energy"]
    types = {r.type for r in treat.event_log.records}
    assert "trade_throttled" in types
