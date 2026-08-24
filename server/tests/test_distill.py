"""LLM→RL蒸留パイプラインのテスト（API不要: heuristicを教師代わりに使用）。"""
import numpy as np

from terrarium.rl.distill import decisions_to_action, behavior_clone
from terrarium.rl.env import NationEnv, OBS_DIM, obs_from_view
from terrarium.rl.nets import PolicyNet
from terrarium.sim.interventions import Scenario
from terrarium.agents.heuristic import HeuristicPolicy


def test_decisions_to_action_maps_budget_and_posture():
    from terrarium.agents.base import Decisions
    d = Decisions(rationale="t", budget={"military": 0.5, "welfare": 0.2, "stockpile": 0.2, "subsidy": 0.1},
                  military_posture="aggressive", rationing=True, propaganda=False)
    a = decisions_to_action(d)
    assert a["budget_idx"] == 1  # fortress
    assert a["posture_idx"] == 2 and a["rationing"] == 1 and a["propaganda"] == 0


def test_distillation_learns_teacher_behavior():
    """heuristic教師のデータでBCすると、教師の行動分布に近づく。"""
    env = NationEnv("default", "SAH", seed=5, horizon=12, scenario=Scenario())
    teacher = HeuristicPolicy()
    data = []
    obs = env.reset()
    done = False
    while not done:
        d = teacher.decide(env.eng.nation_view("SAH"))
        act = decisions_to_action(d)
        data.append({"obs": obs.copy(), "action": act})
        obs, _, done, _ = env.step(act)
    assert len(data) == 12
    net = PolicyNet(obs_dim=OBS_DIM, seed=1)
    # BC前: 教師との一致率
    def acc(net):
        hits = 0
        for s in data:
            out = net.forward(s["obs"])
            hits += int(int(np.argmax(out["budget_logits"])) == s["action"]["budget_idx"])
        return hits / len(data)
    before = acc(net)
    behavior_clone(net, data, epochs=10, lr=3e-3)
    after = acc(net)
    assert after > before, f"BC must increase teacher agreement ({before:.2f} -> {after:.2f})"
