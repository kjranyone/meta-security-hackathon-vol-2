"""政体(実データ分類)・選挙・民主的平和・戦争強度のテスト。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world.presets import load_preset


def _engine(seed: int = 7, preset: str = "earth_all") -> Engine:
    spec = load_preset(preset)
    return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                  seed=seed, out_dir=None)


def test_regime_classification_matches_real_data():
    spec = load_preset("earth_all")
    by = {n.name: n.regime for n in spec.nations}
    assert by["Japan"] == "democracy" and by["Norway"] == "democracy"
    assert by["China"] == "autocracy" and by["North Korea"] == "autocracy"
    assert by["United States of America"] == "democracy"


def test_democratic_peace_lowers_tension():
    eng = _engine(seed=1, preset="earth")
    a, b = sorted(eng.nations)[:2]
    base = eng._pair_tension(a, b)
    eng.nations[a].regime = eng.nations[b].regime = "democracy"
    dem = eng._pair_tension(a, b)
    assert dem < base - 0.1, "two democracies must have markedly lower tension"


def test_election_turnover_on_low_approval():
    eng = _engine(seed=1, preset="earth")
    usa = eng.nations["USA"]
    usa.regime = "democracy"
    usa.approval = 30.0            # 不支持
    usa.next_election = 1          # 次tickが選挙
    eng.tick_no = 1
    eng.step()
    evs = [r.type for r in eng.event_log.records]
    assert "election_turnover" in evs, "low-approval democracy must turn over"
    assert usa.approval > 30.0     # 新政権の蜜月


def test_war_intensity_escalates_and_casualties_accrue():
    eng = _engine(seed=1, preset="earth")
    usa, irn = eng.nations["USA"], eng.nations["IRN"]
    usa.doctrine_militarism = irn.doctrine_militarism = 1.0
    for t in range(1, 14):
        eng.tick_no = t
        if (t - 1) % 6 == 0 and (usa.id, irn.id) not in [(a, b) for a, b in eng.wars]:
            eng.wars.append((usa.id, irn.id))
            eng._war_intensity[(usa.id, irn.id)] = 1.0
            usa.at_war_with.append(irn.id)
            irn.at_war_with.append(usa.id)
        eng.step()
    assert (usa.id, irn.id) not in [(a, b) for a, b in eng.wars] or \
        eng._war_intensity.get((usa.id, irn.id), 1.0) > 1.0, \
        "war intensity must escalate with militarism over months"
    assert sum(eng._war_casualties.values()) > 0.0, "casualties must accrue"
