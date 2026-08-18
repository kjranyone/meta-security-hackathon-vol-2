"""戦略因子（核 etc.）のテスト: 拡散・放棄・抑止・決定論。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world.presets import load_preset


class FixedDoctrine(HeuristicPolicy):
    """任意の因子doctrineを固定表明するpolicy（拡張性の実証も兼ねる）。"""
    def __init__(self, doctrines):
        self.fixed = doctrines

    def decide(self, view):
        d = super().decide(view)
        d.doctrines = dict(self.fixed)
        return d


def _engine(seed=42, ticks=36):
    spec = load_preset("earth")
    pol = {ns.id: HeuristicPolicy() for ns in spec.nations}
    return Engine(spec, pol, seed=seed, out_dir=None), spec


def test_initial_holders_from_preset():
    eng, _ = _engine()
    eng.run(2, Scenario())
    snap = eng.snapshots[-1]
    holders = {nid for nid, n in snap["nations"].items() if "nuclear" in n["factors"]}
    assert holders == {"USA", "RUS", "CHN", "EUR", "IND"}


def test_proliferation_under_threat():
    eng, _ = _engine()
    eng.policies["IRN"] = FixedDoctrine({"nuclear": "pursue"})
    iran = eng.nations["IRN"]
    for _ in range(22):                           # 前提（軍事・安定）を維持し続ける
        iran.military = max(iran.military, 60.0)
        iran.stability = max(iran.stability, 60.0)
        eng.run(1, Scenario())
    evs = [r for r in eng.event_log.records if r.type == "factor_acquired" and r.actor == "IRN"]
    assert evs, "threatened eligible nation must acquire the factor"
    assert "nuclear" in eng.snapshots[-1]["nations"]["IRN"]["factors"]


def test_relinquish_when_collapsing():
    eng, _ = _engine()
    jpn = eng.nations["JPN"]                     # 初期保有国ではないので付与
    jpn.factors.append("nuclear")
    eng.policies["JPN"] = FixedDoctrine({"nuclear": "abandon"})
    eng.run(5, Scenario())
    evs = [r for r in eng.event_log.records if r.type == "factor_relinquished" and r.actor == "JPN"]
    assert evs, "collapsing holder must relinquish"


def test_deterrence_multipliers():
    eng, _ = _engine()
    eng.run(1, Scenario())
    assert eng._deterrence("IRN", "USA") == 0.15   # 非保有→保有
    assert eng._deterrence("USA", "RUS") == 0.03   # 保有同士（MAD）
    assert eng._deterrence("USA", "IRN") is None   # 保有→非保有は抑止対象外


def test_determinism_with_factors():
    a, _ = _engine()
    a.run(10, Scenario())
    b, _ = _engine()
    b.run(10, Scenario())
    assert a.series[-1] == b.series[-1]


def test_god_grant_factor_creates_fact():
    eng, _ = _engine()
    from terrarium.sim.interventions import Intervention
    eng.tick_no = 1
    eng.apply_intervention(Intervention(tick=1, type="grant_factor",
                                        params={"nation": "IRN", "factor": "nuclear"}))
    assert "nuclear" in eng.nations["IRN"].factors
    evs = [r for r in eng.event_log.records if r.type == "god_intervention" and r.data.get("factor") == "nuclear"]
    assert evs


def test_export_control_collective_sanction():
    eng, _ = _engine()
    # USA/CHNを加盟させ、USAがIRNを制裁 → CHNにも伝播する
    eng.nations["USA"].factors.append("export_control")
    eng.nations["CHN"].factors.append("export_control")
    eng.nations["USA"].sanctions_on.append("IRN")
    eng.run(2, Scenario())
    assert "IRN" in eng.nations["CHN"].sanctions_on
    evs = [r for r in eng.event_log.records if r.type == "collective_sanction"]
    assert evs and evs[0].targets[0] == "IRN"
