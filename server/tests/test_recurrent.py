"""再帰型(GRU)戦術AIのテスト: 隠れ状態・BPTT・保存/復元・決定論。"""
import numpy as np

from terrarium.rl.nets import RecurrentPolicyNet, load_net, PolicyNet


def test_hidden_state_changes_output():
    net = RecurrentPolicyNet(obs_dim=48, seed=1)
    rng = np.random.default_rng(0)
    obs = rng.standard_normal(48)
    net.reset_state()
    v1 = net.act(obs, deterministic=True)["value"]
    v2 = net.act(obs, deterministic=True)["value"]
    assert v1 != v2, "rolling hidden state must integrate history"


def test_bptt_is_finite_and_moves_params():
    net = RecurrentPolicyNet(obs_dim=48, seed=2)
    rng = np.random.default_rng(1)
    obs_list = [rng.standard_normal(48) for _ in range(10)]
    acts = [net.act(o) for o in obs_list]
    before = net.Wn.copy()
    net.update_sequence(obs_list, acts, [0.1] * 10, [1.0] * 10)
    assert all(np.isfinite(p).all() for p in net.params)
    assert not np.allclose(before, net.Wn), "BPTT must update recurrent weights"


def test_save_load_roundtrip_and_dispatch():
    import tempfile, pathlib
    net = RecurrentPolicyNet(obs_dim=48, seed=3)
    net.reset_state()
    obs = np.random.default_rng(2).standard_normal(48)
    net.act(obs)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "gru.npz"
        net.save(p)
        loaded = load_net(p)
        assert isinstance(loaded, RecurrentPolicyNet)
        assert np.allclose(loaded.Wn, net.Wn)
        # MLPはkindなしのまま従来どおり
        m = PolicyNet(obs_dim=48, seed=3)
        pm = pathlib.Path(d) / "mlp.npz"
        m.save(pm)
        assert isinstance(load_net(pm), PolicyNet)


def test_runtime_hidden_is_deterministic():
    """同じ重みと観測列なら隠れ状態の伝搬も決定論（IF史の再現性）。"""
    a = RecurrentPolicyNet(obs_dim=48, seed=5)
    b = RecurrentPolicyNet(obs_dim=48, seed=5)
    rng = np.random.default_rng(7)
    seq = [rng.standard_normal(48) for _ in range(6)]
    a.reset_state(); b.reset_state()
    va = [a.act(o, deterministic=True)["value"] for o in seq]
    vb = [b.act(o, deterministic=True)["value"] for o in seq]
    assert va == vb
