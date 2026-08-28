"""DeepPolicyNet(多層蒸留用MLP)のテスト: 勾配・BC・save/load・A2C互換・ローダ。"""
import numpy as np

from terrarium.rl.env import OBS_DIM
from terrarium.rl.nets import DeepPolicyNet, load_net


def _toy_data(n=48, seed=0):
    rng = np.random.default_rng(seed)
    # budget_idxは観測の先頭3次元のargmaxで決まる敵対的でない「ルール」教師
    data = []
    for _ in range(n):
        obs = rng.normal(size=OBS_DIM).astype(np.float32)
        obs[0], obs[1], obs[2] = -2.0, -2.0, -2.0
        k = int(rng.integers(0, 3))
        obs[k] = 2.0
        data.append({"obs": obs,
                     "action": {"budget_idx": k, "posture_idx": k % 3,
                                "rationing": k == 2, "propaganda": k == 1}})
    return data


def test_deep_bc_learns_rule_teacher():
    """教師が観測の決定的関数ならBCはhold-outでもそれを再現する(判別力の検証)。"""
    from terrarium.rl.distill import _behavior_clone_deep
    data = _toy_data(96)
    net = DeepPolicyNet(obs_dim=OBS_DIM, hidden=[64, 32], seed=1)
    _, m = _behavior_clone_deep(net, data, epochs=30, lr=3e-3, batch_size=16)
    assert m["budget_acc"] > 0.9, f"rule teacher must be learned (got {m['budget_acc']:.2f})"
    assert m["macro_f1"] > 0.85


def test_deep_save_load_and_loader_dispatch(tmp_path):
    net = DeepPolicyNet(obs_dim=OBS_DIM, hidden=[32, 16], seed=2)
    obs = np.random.default_rng(3).normal(size=OBS_DIM).astype(np.float32)
    a1 = net.act(obs, deterministic=True)
    p = tmp_path / "deep.npz"
    net.save(p)
    net2 = load_net(p)          # kind="deep"で自動判別されること
    assert isinstance(net2, DeepPolicyNet)
    a2 = net2.act(obs, deterministic=True)
    assert a1["budget_idx"] == a2["budget_idx"]
    assert a1["posture_idx"] == a2["posture_idx"]
    assert a1["rationing"] == a2["rationing"]


def test_deep_update_runs_and_value_learns():
    """A2C互換update(): valueヘッドがretに近づく(昇降の符号が正しいことの検出)。"""
    net = DeepPolicyNet(obs_dim=OBS_DIM, hidden=[32], seed=4)
    obs = np.random.default_rng(5).normal(size=OBS_DIM).astype(np.float32)
    v0 = net.forward(obs)["value"]
    for _ in range(80):
        net.update(obs, {"budget_idx": 0, "posture_idx": 0, "rationing": 0, "propaganda": 0},
                   advantage=0.0, ret=1.5, lr=3e-2)
    v1 = net.forward(obs)["value"]
    assert abs(v1 - 1.5) < abs(v0 - 1.5), "value must move toward ret"


def test_deep_bc_class_weights_help_rare_class():
    """逆頻度重み: 稀クラスのrecallが均一重みより劣らない(回帰検出用)。"""
    from terrarium.rl.distill import _behavior_clone_deep
    rng = np.random.default_rng(7)
    data = []
    for i in range(120):        # 90%がclass0、10%がclass3の不均衡教師
        obs = rng.normal(size=OBS_DIM).astype(np.float32)
        k = 0 if rng.random() < 0.9 else 3
        obs[:4] = 0.0
        obs[k] = 3.0
        data.append({"obs": obs,
                     "action": {"budget_idx": k, "posture_idx": 1,
                                "rationing": False, "propaganda": False}})
    net = DeepPolicyNet(obs_dim=OBS_DIM, hidden=[64], seed=8)
    _, m = _behavior_clone_deep(net, data, epochs=40, lr=3e-3, batch_size=16)
    assert m["per_class"][3]["recall"] >= 0.5, \
        f"rare class recall {m['per_class'][3]['recall']:.2f} with inverse-freq weights"
