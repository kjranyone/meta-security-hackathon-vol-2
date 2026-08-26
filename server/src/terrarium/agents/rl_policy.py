"""Inference policy backed by a trained RL tactical net."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..rl.env import action_to_decisions, obs_from_view
from ..rl.nets import load_net
from .base import Decisions, NationView

SERVER_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEIGHTS = SERVER_ROOT / "models"


class RLPolicy:
    """Deterministic (argmax) tactical policy: budget preset + posture +
    rationing/propaganda from the learned MLP."""

    def __init__(self, nation_id: str, weights: str | Path | None = None):
        path = Path(weights) if weights else DEFAULT_WEIGHTS / f"rl_{nation_id}.npz"
        if not path.exists():
            raise FileNotFoundError(
                f"RL weights not found: {path}. Train first: "
                f"uv run python -m terrarium.rl.train --nation {nation_id}")
        self.net = load_net(path)
        self.nation_id = nation_id
        self.weights_path = str(path)

    def decide(self, view: NationView) -> Decisions:
        obs = obs_from_view(view)
        # 旧モデル(小さい観測次元)との後方互換: 次元を合わせる
        want = self.net.W1.shape[0]
        if obs.shape[0] < want:
            obs = np.concatenate([obs, np.zeros(want - obs.shape[0], dtype=np.float32)])
        elif obs.shape[0] > want:
            obs = obs[:want]
        # 再帰型の場合、隠れ状態はこの政策オブジェクトの寿命の間ローリングする
        # （世界の履歴の内部表現。世界再構築でリセット=決定論を保つ）
        action = self.net.act(obs, deterministic=True)
        d = action_to_decisions(action)
        d.rationale = f"RL tactical policy ({self.weights_path})"
        return d
