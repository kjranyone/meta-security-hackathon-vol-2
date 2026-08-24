"""外交のエピソード記憶と政策履歴のテスト。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.agents.llm import build_user_prompt
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world.presets import load_preset


def _engine(seed: int = 7, preset: str = "earth") -> Engine:
    spec = load_preset(preset)
    return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                  seed=seed, out_dir=None)


def test_threat_creates_bilateral_memory():
    """脅迫は、脅した側と脅された側の両方の記憶に載る（i_actedで区別）。"""
    eng = _engine(seed=1)
    eng.nations["USA"].trust["IRN"] = -60.0
    eng.nations["USA"].aggression = 0.8
    eng._apply_decisions({})
    # heuristicのdiplomacyは_apply_decisions({})では空 — 直接イベントを打つ
    from terrarium.agents.base import Decisions, DiplomaticAction
    eng._decisions_fresh = True
    eng._dec_elapsed_hours = 730.0
    eng._apply_decisions({
        "USA": Decisions(rationale="t", budget={}, military_posture="neutral",
                         diplomacy=[DiplomaticAction(kind="threaten", target="IRN")]),
    })
    mem_usa = eng._bilateral_memory("USA")
    mem_irn = eng._bilateral_memory("IRN")
    assert any(m["event"] == "threat" and m["i_acted"] for m in mem_usa)
    assert any(m["event"] == "threat" and not m["i_acted"] and "USA" in m["with"]
               for m in mem_irn), "the target must remember being threatened"
    v = eng.nation_view("IRN")
    assert any(m["event"] == "threat" for m in v.memory)


def test_decision_history_accumulates():
    eng = _engine(seed=1)
    eng.run(6, Scenario())
    v = eng.nation_view("USA")
    assert len(v.last_decisions) >= 3, "decision memory must accumulate"
    assert all("tick" in d and "posture" in d for d in v.last_decisions)


def test_llm_prompt_contains_memory():
    eng = _engine(seed=1)
    eng.run(8, Scenario())
    v = eng.nation_view("CHN")
    prompt = build_user_prompt("test persona", v)
    assert "外交・紛争履歴" in prompt
    assert "過去の決定" in prompt
