"""リアリズム層の力学テスト: 失業・為替・外貨準備・CO2・インフラ。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario, load_scenario
from terrarium.world.presets import load_preset


def _engine(preset="earth", scenario=None, ticks=36, seed=42):
    spec = load_preset(preset)
    pol = {ns.id: HeuristicPolicy() for ns in spec.nations}
    eng = Engine(spec, pol, seed=seed, out_dir=None)
    eng.run(ticks, scenario or Scenario())
    return eng


def test_unemployment_rises_under_closure():
    eng = _engine(scenario=load_scenario("scenarios/earth_triple_crisis.yaml"))
    base = _engine(ticks=12)
    crisis_u = eng.snapshots[-1]["metrics"]["mean_unemployment"]
    base_u = base.snapshots[-1]["metrics"]["mean_unemployment"]
    assert crisis_u > base_u, f"crisis {crisis_u} should exceed baseline {base_u}"


def test_default_depreciates_fx_and_reserves():
    eng = _engine(scenario=load_scenario("scenarios/earth_financial_crisis.yaml"))
    defaults = [r for r in eng.event_log.records if r.type == "sovereign_default"]
    assert defaults, "financial crisis must produce defaults"
    jpn = eng.snapshots[-1]["nations"]["JPN"]
    assert jpn["fx"] < 1.0, "default must depreciate the currency"
    assert jpn["fx_reserves"] < 8.0


def test_co2_accumulates_and_renew_reduces_it():
    eng = _engine(ticks=6)
    assert eng.snapshots[-1]["metrics"]["global_co2"] > 0
    saudi = eng.snapshots[-1]["nations"]["SAU"]
    france_like = eng.snapshots[-1]["nations"]["EUR"]
    assert saudi["co2_cum"] > france_like["co2_cum"], "fossil-heavy producers emit more"


def test_infra_follows_budget_and_bounded():
    eng = _engine(ticks=24)
    for nid, n in eng.snapshots[-1]["nations"].items():
        assert 0.5 <= n["infra"] <= 1.25, f"{nid} infra {n['infra']} out of bounds"


def test_determinism_with_realism_layer():
    a = _engine(ticks=8)
    b = _engine(ticks=8)
    assert a.series[-1] == b.series[-1]
    assert a.snapshots[-1]["nations"]["JPN"] == b.snapshots[-1]["nations"]["JPN"]
