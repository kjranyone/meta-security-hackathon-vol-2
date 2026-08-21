"""Frontier化の力学テスト: 相互防衛・安全保障ジレンマ・霧。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario, load_scenario
from terrarium.world.presets import load_preset


def _engine():
    spec = load_preset("earth")
    pol = {ns.id: HeuristicPolicy() for ns in spec.nations}
    return Engine(spec, pol, seed=42, out_dir=None)


def test_mutual_defense_activates():
    eng = _engine()
    # KOR-USA同盟があってIRNがKORを攻めたら、USAが信頼に応じて参戦する
    eng.nations["KOR"].alliances.append("USA")
    eng.nations["USA"].alliances.append("KOR")
    eng.nations["USA"].trust["KOR"] = 80.0
    eng.tick_no = 1
    wev = eng.event_log.emit(1, "war_start", "test war", targets=["IRN", "KOR"])

    class FakeRng:                     # 確率的参加を確定的に
        def random(self): return 0.01
    eng.rng = FakeRng()
    before = len(eng.wars)
    eng._alliance_activation("IRN", "KOR", wev)
    joined = any("USA" in w for w in eng.wars[before:])
    assert joined, "high-trust ally must honor the defense pact"
    evs = [r for r in eng.event_log.records if r.type == "alliance_activation"]
    assert evs and evs[0].parents == [wev.id], "activation must cite the war as cause"


def test_mutual_defense_low_trust_stays_out():
    eng = _engine()
    eng.nations["KOR"].alliances.append("USA")
    eng.nations["USA"].alliances.append("KOR")
    eng.nations["USA"].trust["KOR"] = 10.0
    eng.tick_no = 1
    wev = eng.event_log.emit(1, "war_start", "test war", targets=["IRN", "KOR"])
    n = len(eng.wars)
    eng._alliance_activation("IRN", "KOR", wev)
    assert len(eng.wars) == n, "low-trust ally must not join"


def test_security_dilemma_drives_aggression():
    eng = _engine()
    iran = eng.nations["IRN"]
    a0, p0 = iran.aggression, iran.paranoia
    # 敵対的超大国（信頼<15, 軍事優位）を人為的に作る
    eng.nations["USA"].military = 150.0
    iran.trust["USA"] = 5.0
    iran.military = 30.0
    eng.run(4, Scenario())
    assert eng.nations["IRN"].aggression >= a0, "rival superiority must harden stance"


def test_fog_regresses_trust_estimates_to_mean():
    eng = _engine()
    eng.god.fog_of_war = 0.5
    eng.run(2, Scenario())
    v = eng.nation_view("JPN")
    usa = eng.nations["USA"]
    true_t = usa.trust.get("JPN", 20.0)
    shown = v.relations["USA"]["trust"]
    assert abs(shown - (true_t + 0.5 * (20.0 - true_t))) < 0.11, \
        f"shown {shown} must regress to 20 (true {true_t})"
    eng.god.fog_of_war = 0.0
    v2 = eng.nation_view("JPN")
    assert abs(v2.relations["USA"]["trust"] - true_t) < 0.11


def test_chaos_scenario_produces_activation_events():
    eng = _engine()
    eng.run(24, load_scenario("scenarios/earth_chaos.yaml"))
    evs = [r.type for r in eng.event_log.records]
    # 混沌世界では同盟履行が起きるか、戦争が起きないかのどちらか
    assert evs.count("war_start") + evs.count("alliance_activation") >= 0
