"""安全保障パラメータ拡張のテスト: 思想・核態勢・軍拡・講和・内戦・軍備管理。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world.presets import load_preset


def _engine(seed: int = 7, preset: str = "default") -> Engine:
    spec = load_preset(preset)
    return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                  seed=seed, out_dir=None)


def test_revisionism_raises_tension():
    eng = _engine(seed=1)
    a, b = sorted(eng.nations)[:2]
    base = eng._pair_tension(a, b)
    eng.nations[a].doctrine_revisionism = 0.9
    eng.nations[b].doctrine_revisionism = 0.9
    high = eng._pair_tension(a, b)
    assert high > base + 0.05, f"revisionism must raise tension ({base:.3f} -> {high:.3f})"


def test_nuclear_posture_changes_deterrence():
    """counterforce は抑止を侵食し、NFU は安定を強める。"""
    eng = _engine(seed=1, preset="earth")
    usa, irn = "USA", "IRN"
    eng.nations[usa].factors.append("nuclear")
    eng.nations[irn].factors.append("nuclear")
    eng.nations[usa].nuclear_posture = "counterforce"
    det_cf = eng._deterrence(usa, irn)
    eng.nations[usa].nuclear_posture = "mad"
    det_mad = eng._deterrence(usa, irn)
    eng.nations[usa].nuclear_posture = "nfu"
    det_nfu = eng._deterrence(usa, irn)
    assert det_cf < det_mad < det_nfu, f"{det_cf} < {det_mad} < {det_nfu} expected"


def test_richardson_arms_race_reaction():
    """敵性大国の軍備増強に、軍事偏重の政府だけが過剰反応する。"""
    eng = _engine(seed=1)
    a, b = sorted(eng.nations)[:2]
    for nid in (a, b):
        eng.nations[nid].trust = {o: -60.0 for o in eng.nations if o != nid}
    eng.nations[a].doctrine_militarism = 1.0
    eng.nations[b].doctrine_militarism = 0.0
    m_a0, m_b0 = eng.nations[a].military, eng.nations[b].military
    # bが軍拡した直後のtickを打つ
    eng.tick_no = 0
    eng._mil_prev[b] = eng.nations[b].military - 5.0   # bは先tickに+5拡張した扱い
    eng.step()
    assert eng.nations[a].military > m_a0, "militarist must react to rival surge"
    growth_reactor = eng.nations[a].military - m_a0
    # 統制: 敵性関係を切れば反応は消える（同じbudgetでも）
    eng2 = _engine(seed=1)
    x, y = sorted(eng2.nations)[:2]
    eng2.nations[x].doctrine_militarism = 1.0
    eng2.nations[x].trust = {o: 60.0 for o in eng2.nations if o != x}
    eng2.tick_no = 0
    eng2._mil_prev[y] = eng2.nations[y].military - 5.0
    m_x0 = eng2.nations[x].military
    eng2.step()
    assert eng2.nations[x].military - m_x0 <= growth_reactor + 1e-9, \
        "non-rival surge must not trigger the same reaction"


def test_peace_settlement_ends_mismatched_war():
    """力の差が大きい戦争は交渉で終わる（疲弊衰亡とは別の終わり方）。"""

    class SettleRng:
        def __init__(self): self.n = 0
        def random(self): return 0.0      # 全ハザードを通す
        def triangular(self, lo, hi, mode): return lo
        def uniform(self, a, b): return a

    eng = _engine(seed=1, preset="earth")
    eng.rng = SettleRng()
    eng.wars.append(("USA", "TWN"))
    eng.nations["USA"].at_war_with.append("TWN")
    eng.nations["TWN"].at_war_with.append("USA")
    eng.tick_no = 0
    eng.step()
    assert any(r.type == "peace_settlement" for r in eng.event_log.records), \
        "mismatched war must end in a negotiated settlement"


def test_insurgency_fires_under_grievance():
    class FireRng:
        def random(self): return 0.0      # ハザードを確定的に通す
        def triangular(self, lo, hi, mode): return mode
        def uniform(self, a, b): return (a + b) / 2

    eng = _engine(seed=3, preset="earth_all")
    eng.rng = FireRng()
    frag = min(eng.nations.values(), key=lambda n: n.stability)
    eng.tick_no = 0
    frag.stability = 5.0
    eng.step()
    assert any(r.type == "insurgency" and r.actor == frag.id
               for r in eng.event_log.records), \
        "governance collapse must trigger insurgency immediately (forced hazard)"


def test_nuclear_proliferation_cascade():
    """敵性核保有国の出現が、対抗する核追求（heuristic doctrine）を誘発する。"""
    from terrarium.agents.heuristic import HeuristicPolicy
    spec = load_preset("earth")
    pol = HeuristicPolicy()

    class V:
        me = {"factors": [], "stability": 60.0, "at_war_with": []}
        relations = {"USA": {"nuclear": True, "trust": -20.0, "alliance": False,
                             "war": False, "sanction": False}}

    assert pol._doctrines(V()).get("nuclear") == "pursue", \
        "rival nuclear acquisition must trigger pursuit doctrine"
