"""創発するイデオロギー圏（宗教戦争の中立モデル化）のテスト。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Scenario
from terrarium.world.presets import load_preset


def _engine(seed: int = 7, preset: str = "default") -> Engine:
    spec = load_preset(preset)
    return Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                  seed=seed, out_dir=None)


def test_religious_tech_adoption_sets_ideology():
    eng = _engine(seed=1)
    a = sorted(eng.nations)[0]
    eng.nations[a].ideology = "secular"
    eng._adopt_tech(a, "ai_religion", forced=True)
    assert eng.nations[a].ideology == "ai_cult"
    eng._adopt_tech(a, "techno_nationalism", forced=True)
    assert eng.nations[a].ideology == "techno_nationalist"


def test_ideological_friction_raises_tension():
    eng = _engine(seed=1)
    a, b = sorted(eng.nations)[:2]
    base = eng._pair_tension(a, b)
    eng.nations[a].ideology = "ai_cult"
    eng.nations[b].ideology = "techno_nationalist"
    friction = eng._pair_tension(a, b)
    assert friction > base + 0.1, f"different blocs must raise tension ({base:.3f} -> {friction:.3f})"
    # 同じ圏ならむしろ結束する
    eng.nations[b].ideology = "ai_cult"
    cohesion = eng._pair_tension(a, b)
    assert cohesion < friction, "same bloc must reduce tension vs different bloc"


def test_ideological_war_is_flagged():
    eng = _engine(seed=1)
    a, b = sorted(eng.nations)[:2]
    eng.nations[a].ideology = "ai_cult"
    eng.nations[b].ideology = "techno_nationalist"
    eng._start_war(a, b, 0.9)
    ev = [r for r in eng.event_log.records if r.type == "war_start"][-1]
    assert ev.data.get("ideological") is True and "イデオロギー" in ev.text


def test_ideology_emerges_in_long_world():
    """72ヶ月世界では宗教系技術が創発し、イデオロギー圏が生まれる。"""
    eng = _engine(seed=11, preset="earth")
    eng.run(40, Scenario())
    blocs = sum(1 for n in eng.nations.values() if n.ideology != "secular")
    assert blocs >= 1, "socio-tech emergence must create ideological blocs"
