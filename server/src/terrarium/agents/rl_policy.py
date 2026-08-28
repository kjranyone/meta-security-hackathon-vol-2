"""Inference policy backed by a trained RL tactical net."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..rl.env import OBS_SEM2_LIVE_IDX, action_to_decisions, obs_from_view
from ..rl.nets import load_net
from .base import Decisions, NationView

SERVER_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEIGHTS = SERVER_ROOT / "models"

# 重みパス→ネットの共有キャッシュ。全国家配備(ALL)で同一モデルを載せる時、
# 国ごとにload_netすると176カ国×50MB≈8GB超でOOMする。MLPの推論は状態を
# 持たないため共有安全。再帰型(隠れ状態が国ごとにローリング)は共有しない。
_NET_CACHE: dict[str, object] = {}


class RLPolicy:
    """Deterministic (argmax) tactical policy: budget preset + posture +
    rationing/propaganda from the learned MLP."""

    def __init__(self, nation_id: str, weights: str | Path | None = None):
        path = Path(weights) if weights else DEFAULT_WEIGHTS / f"rl_{nation_id}.npz"
        if not path.exists():
            raise FileNotFoundError(
                f"RL weights not found: {path}. Train first: "
                f"uv run python -m terrarium.rl.train --nation {nation_id}")
        key = str(path.resolve())
        net = _NET_CACHE.get(key)
        if net is None:
            net = load_net(path)
            if type(net).__name__ != "RecurrentPolicyNet":
                _NET_CACHE[key] = net
        self.net = net
        self.nation_id = nation_id
        self.weights_path = str(path)

    def decide(self, view: NationView) -> Decisions:
        obs = obs_from_view(view)
        # 旧モデル(小さい観測次元)との後方互換: 次元を合わせる
        # (GRUはW1を持たないためobs_dim属性を優先する)
        want = getattr(self.net, "obs_dim", None)
        if want is None:
            want = self.net.W1.shape[0]
        if obs.shape[0] < want:
            obs = np.concatenate([obs, np.zeros(want - obs.shape[0], dtype=np.float32)])
        elif obs.shape[0] > want:
            obs = obs[:want]
        # 観測意味sem1の旧モデルは war_intensity/refugee 次元が常に0で訓練されている。
        # 0でマスクして訓練時の入力分布を維持する（コミット済みrunのbit等価のため）
        if getattr(self.net, "obs_sem", 1) < 2:
            for i in OBS_SEM2_LIVE_IDX:
                if i < obs.shape[0]:
                    obs[i] = 0.0
        # 再帰型の場合、隠れ状態はこの政策オブジェクトの寿命の間ローリングする
        # （世界の履歴の内部表現。世界再構築でリセット=決定論を保つ）
        action = self.net.act(obs, deterministic=True)
        d = action_to_decisions(action)
        d.rationale = f"RL tactical policy ({self.weights_path})"
        return d
