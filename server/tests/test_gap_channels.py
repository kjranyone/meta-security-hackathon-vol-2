"""残るギャップのチャネル実装のテスト: 慢性疑心(偽情報増強)と平時サイバー。"""
from terrarium.agents.heuristic import HeuristicPolicy
from terrarium.sim.engine import Engine
from terrarium.sim.interventions import Intervention, Scenario
from terrarium.world.presets import load_preset


def _engine(preset="default", seed=0):
    spec = load_preset(preset)
    policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
    return Engine(spec, policies, seed=seed, out_dir=None)


def _run(eng, ticks, scenario=None):
    scenario = scenario or Scenario()
    schedule = sorted(scenario.interventions, key=lambda i: i.tick)
    for t in range(ticks):
        eng.tick_no = t
        for iv in schedule:
            if iv.tick == t:
                eng.apply_intervention(iv)
        eng.step()


def test_paranoia_decays_toward_base():
    eng = _engine(seed=3)
    nat = eng.nations["VLT"]
    nat.paranoia = 0.9
    base = nat.base_paranoia
    _run(eng, 24)
    assert nat.paranoia < 0.9, "疑心は放置すれば消退する"
    assert nat.paranoia > base - 0.05, "基準値を下回って消失はしない"


def test_disinfo_dose_response_and_domestic_cost():
    """疑心は強度に単調。慢性疑心(>0.55)は安定を毀損する(国内チャネル)。"""
    # (a) 用量反応: 反復キャンペーン(t1, t8)で疑心の立ち上がりが単調
    paranoia_peak = {}
    for intensity in (0.0, 1.5, 3.0):
        eng = _engine(seed=5)
        ivs = [] if intensity == 0 else [
            Intervention(tick=t, type="disinfo", params={"target": "VLT",
                                                         "intensity": intensity})
            for t in (1, 8)]
        peak, scen = 0.0, Scenario(interventions=ivs)
        for t in range(18):
            eng.tick_no = t
            for iv in scen.interventions:
                if iv.tick == t:
                    eng.apply_intervention(iv)
            eng.step()
            peak = max(peak, eng.nations["VLT"].paranoia)
        paranoia_peak[intensity] = peak
    assert paranoia_peak[3.0] > paranoia_peak[1.5] > paranoia_peak[0.0], \
        f"疑心は強度に単調 {paranoia_peak}"

    # (b) チャネル直接検証: 慢性疑心0.8は安定を対照より下げる
    eng_t = _engine(seed=11)
    eng_c = _engine(seed=11)
    eng_t.nations["VLT"].paranoia = 0.8
    for t in range(24):
        eng_t.tick_no = eng_c.tick_no = t
        eng_t.step()
        eng_c.step()
    # paranoiaはbaseへ回帰するため効果は減衰するが、24ヶ月で差が残る
    assert eng_t.nations["VLT"].stability < eng_c.nations["VLT"].stability, \
        "慢性疑心は安定を毀損する"


def test_peacetime_cyber_erodes_infra():
    """cyber_arsenal保有国は低信頼相手に平時サイバーを行う(常設チャネル)。"""
    eng = _engine(preset="earth", seed=7)
    eng._adopt_tech("USA", "cyber_arsenal", forced=True)
    for other in ("IRN", "RUS", "CHN", "TWN", "PRK" if "PRK" in eng.nations else "IDN"):
        eng.nations["USA"].trust[other] = -40.0
        eng.nations[other].trust["USA"] = -40.0
    infra0 = {o: eng.nations[o].infra for o in ("IRN", "RUS", "CHN")}
    _run(eng, 60)
    evs = [r for r in eng.event_log.records
           if r.type == "cyber_attack" and r.data.get("peacetime")]
    assert evs, "平時サイバーイベントが発生するはず(5対×60ヶ月)"
    # 技術は有機採用で他国(CHN等)も持つため、USA発のものが少なくとも1つあることを検証
    assert any(r.actor == "USA" for r in evs)
    assert any(eng.nations[o].infra < infra0[o] for o in infra0), "インフラの漸減"


def test_peacetime_cyber_requires_low_trust():
    """信頼が高い相手には平時サイバーは発生しない(負の対照)。"""
    eng = _engine(preset="earth", seed=7)
    eng._adopt_tech("USA", "cyber_arsenal", forced=True)
    for other in eng.nations:
        if other != "USA":
            eng.nations["USA"].trust[other] = 60.0
    _run(eng, 60)
    evs = [r for r in eng.event_log.records
           if r.type == "cyber_attack" and r.data.get("peacetime")]
    assert not evs
