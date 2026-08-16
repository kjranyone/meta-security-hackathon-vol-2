"""Inference policy backed by a trained RL tactical net."""
from __future__ import annotations

from pathlib import Path

from ..rl.env import action_to_decisions, obs_from_view
from ..rl.nets import PolicyNet
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
        self.net = PolicyNet.load(path)
        self.nation_id = nation_id
        self.weights_path = str(path)

    def decide(self, view: NationView) -> Decisions:
        obs = obs_from_view(view)
        action = self.net.act(obs, deterministic=True)
        d = action_to_decisions(action)
        d.rationale = f"RL tactical policy ({self.weights_path})"
        return d
