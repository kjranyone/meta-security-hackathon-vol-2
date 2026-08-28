"""初期同盟網(WorldSpec.initial_alliances)のテスト。

earth_jpn(米国ハブの同盟網)で「在日米軍の巻き込み」型リスクの経路を検証する:
米中開戦 → 日本は同盟国(米)の協議対象になり、信頼と遵守度に応じて参戦する。
連鎖の深さは1(設計どおり): 二次連鎖(米国の参戦を経由した日本の巻き込み)は
発生しない — 巻き込みを測るには当事者が直接交戦する必要がある。
"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.world.presets import load_preset


def _engine(preset: str, seed: int = 0) -> Engine:
    spec = load_preset(preset)
    policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
    return Engine(spec, policies, seed=seed, out_dir=None)


def test_alliance_web_wired_and_trusted():
    eng = _engine("earth_jpn")
    assert "USA" in eng.nations["JPN"].alliances
    assert "JPN" in eng.nations["USA"].alliances
    assert eng.nations["JPN"].trust["USA"] >= 35.0, \
        "宣言同盟は協議の発火条件(trust>=35)を満たす信頼を持つこと"
    # 凍結済みearthは無同盟のまま(bit再現の維持)
    eng0 = _engine("earth")
    assert eng0.nations["JPN"].alliances == []
    assert eng0.nations["JPN"].trust["USA"] == 20.0


def test_usa_china_war_consults_japan():
    """米中開戦時、日本は協議スケジュールに入る(決定論的部分)。"""
    eng = _engine("earth_jpn", seed=1)
    eng._start_war("USA", "CHN", tension=1.5)
    pend_jpn = [p for p in eng._pending_alliance if p["x"] == "JPN"]
    assert pend_jpn, "日本(米国の同盟国)は米中戦争の協議対象になる"
    assert pend_jpn[0]["b"] == "USA" and pend_jpn[0]["a"] == "CHN"


def test_alliance_activation_fires_for_high_trust_ally():
    """高信頼・高遵守の同盟国は何らかのseedで参戦する(確率的発動の実在)。"""
    fired = 0
    for seed in range(24):
        eng = _engine("earth_jpn", seed=seed)
        jpn = eng.nations["JPN"]
        jpn.trust["USA"] = 100.0
        jpn.doctrine_treaty_fidelity = 1.0
        eng._start_war("USA", "CHN", tension=1.5)
        for t in (1, 2, 3):   # step()はtickを進めないので明示的に進める
            eng.tick_no = t
            eng.step()
        acts = [r for r in eng.event_log.records if r.type == "alliance_activation"]
        if any(r.actor == "JPN" for r in acts):
            fired += 1
            # 発動イベントは戦争イベントを因果parentに持つ
            assert any(p is not None for p in acts[0].parents)
    assert fired >= 1, "24 seed中至少1つは同盟履行(日本の参戦)が発生するはず"


def test_no_alliance_no_consultation():
    """同盟網なし(earth)では協議が発生しない(負の対照)。"""
    eng = _engine("earth", seed=1)
    eng._start_war("USA", "CHN", tension=1.5)
    assert not [p for p in eng._pending_alliance if p["x"] == "JPN"]
