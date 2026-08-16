"""RL environment: one learner nation inside the Terrarium engine.

Other nations run the deterministic heuristic policy, so the environment is
a single-agent MDP (self-play is a natural extension: swap in other learners).

Observation and reward are built only from NationView + engine state so that
inference (RLPolicy.decide) and training see exactly the same features.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..agents.base import Decisions, NationView
from ..agents.heuristic import HeuristicPolicy
from ..sim.engine import Engine
from ..sim.interventions import Scenario
from ..world.presets import load_preset

OBS_DESC = [
    "stock_energy", "stock_food", "stock_chips", "stock_minerals", "stock_space",
    "log_gdp", "inflation", "stability", "approval", "military",
    "aggression", "paranoia", "at_war", "collapsed",
    "price_energy", "price_food", "price_chips", "price_minerals", "price_space",
    "god_trade_eff", "god_ai_aggr",
    "mean_trust", "alliances", "sanctions_on", "techs", "tick_frac",
]
OBS_DIM = len(OBS_DESC)
COMMODITIES = ("energy", "food", "chips", "minerals", "space")


def obs_from_view(view: NationView) -> np.ndarray:
    me, prices, god = view.me, view.prices, view.god_params
    stocks = me.get("stocks", {})
    rels = list(view.relations.values())
    mean_trust = float(np.mean([r.get("trust", 0.0) for r in rels])) / 100.0 if rels else 0.0
    alliances = sum(1 for r in rels if r.get("alliance")) / max(1, len(rels))
    sanctions = sum(1 for r in rels if r.get("sanction")) / max(1, len(rels))
    obs = np.array([
        *[min(stocks.get(c, 0.0), 6.0) / 6.0 for c in COMMODITIES],
        float(np.log10(max(me.get("gdp", 0.1), 0.1))) / 2.0,
        float(me.get("inflation", 0.0)) * 10.0,
        float(me.get("stability", 50.0)) / 100.0,
        float(me.get("approval", 50.0)) / 100.0,
        float(me.get("military", 50.0)) / 100.0,
        float(me.get("aggression", 0.3)),
        float(me.get("paranoia", 0.3)),
        1.0 if me.get("at_war_with") else 0.0,
        1.0 if me.get("collapsed") else 0.0,
        *[float(prices.get(c, 1.0)) for c in COMMODITIES],
        float(god.get("trade_efficiency", 1.0)) - 1.0,
        float(god.get("ai_aggression", 1.0)) - 1.0,
        mean_trust, alliances, sanctions,
        len(me.get("techs", [])) / 13.0,
        view.tick / 36.0,
    ], dtype=np.float32)
    return np.clip(obs, -5.0, 5.0)


class ExternalPolicy:
    """Policy slot whose decision is injected from outside (the RL loop)."""

    def __init__(self) -> None:
        self.pending = Decisions(rationale="rl tactical")

    def decide(self, view: NationView) -> Decisions:
        return self.pending


def action_to_decisions(action: dict) -> Decisions:
    from .nets import BUDGET_PRESETS, POSTURES
    return Decisions(
        budget=dict(BUDGET_PRESETS[action["budget_idx"]]),
        diplomacy=[],
        military_posture=POSTURES[action["posture_idx"]],
        rationing=bool(action["rationing"]),
        propaganda=bool(action["propaganda"]),
        rationale="RL tactical allocation",
    )


class NationEnv:
    """gym-style single-agent env over the engine (1 tick = 1 step)."""

    def __init__(self, preset: str, nation_id: str, seed: int = 0,
                 horizon: int = 24, scenario: Optional[Scenario] = None):
        self.preset = preset
        self.nation_id = nation_id
        self.seed = seed
        self.horizon = horizon
        self.scenario = scenario or Scenario()
        self._ep = 0
        self.learner = ExternalPolicy()
        self.eng: Optional[Engine] = None
        self._prev = None

    def _build(self) -> Engine:
        spec = load_preset(self.preset)
        policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
        policies[self.nation_id] = self.learner
        eng = Engine(spec, policies, seed=self.seed * 100003 + self._ep, out_dir=None)
        return eng

    # ------------------------------------------------------------------ api
    def reset(self) -> np.ndarray:
        self._ep += 1
        self.eng = self._build()
        self._prev = self._snapshot_reward_state()
        return obs_from_view(self.eng.nation_view(self.nation_id))

    def step(self, action: dict):
        eng = self.eng
        self.learner.pending = action_to_decisions(action)
        eng.tick_no = eng.snapshots[-1]["tick"] + 1 if eng.snapshots else 0
        # apply due scenario interventions
        for iv in self.scenario.interventions:
            if iv.tick == eng.tick_no:
                eng.apply_intervention(iv)
        eng.step()
        obs = obs_from_view(eng.nation_view(self.nation_id))
        reward = self._reward()
        nat = eng.nations[self.nation_id]
        done = eng.tick_no >= self.horizon - 1 or nat.collapsed
        info = {"tick": eng.tick_no, "collapsed": nat.collapsed}
        self._prev = self._snapshot_reward_state()
        return obs, reward, done, info

    # ---------------------------------------------------------------- reward
    def _snapshot_reward_state(self) -> dict:
        nat = self.eng.nations[self.nation_id]
        return {
            "log_gdp": float(np.log(max(nat.gdp, 0.1))),
            "stability": nat.stability,
            "approval": nat.approval,
            "war": len(nat.at_war_with),
            "collapsed": nat.collapsed,
            "min_stock": min(nat.stocks.values()),
        }

    def _reward(self) -> float:
        nat = self.eng.nations[self.nation_id]
        cur = self._snapshot_reward_state()
        r = 0.0
        r += 20.0 * (cur["log_gdp"] - self._prev["log_gdp"])
        r += 0.30 * (cur["stability"] - self._prev["stability"])
        r += 0.10 * (cur["approval"] - self._prev["approval"])
        r -= 0.40 * cur["war"]
        # shortage events hitting this nation this tick (dominant penalty:
        # rationing/hoarding only matter insofar as they prevent these)
        for rec in self.eng.event_log.records:
            if rec.tick == self.eng.tick_no and rec.type == "shortage" and (rec.actor == self.nation_id or self.nation_id in rec.targets):
                r -= 2.0
        if cur["collapsed"] and not self._prev["collapsed"]:
            r -= 8.0
        return float(r)
