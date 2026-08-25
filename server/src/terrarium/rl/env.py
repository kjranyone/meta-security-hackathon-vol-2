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
    # --- トレンド観測（戦術層も時系列を見る） ---
    "mom_energy_t3", "mom_food_t3", "mom_chips_t3", "mom_minerals_t3", "mom_space_t3",
    "mom_energy_t12", "mom_food_t12", "mom_chips_t12", "mom_minerals_t12", "mom_space_t12",
    "me_gdp_t12", "me_unemp_t12", "me_debt_t12", "me_fx_t12",
    "world_gdp_t12",
    # --- 思想・ドクトリン（自国の性質。政策の異質性が観測に入る） ---
    "doc_risk", "doc_militarism", "doc_revisionism", "doc_vengeance",
    "doc_treaty_fidelity", "posture_counterforce", "posture_nfu",
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
    # トレンド特徴量（view.trends から。無い世界では0=変化なし）
    tp = view.trends.get("prices", {}) if hasattr(view, "trends") else {}
    tm = view.trends.get("me", {}) if hasattr(view, "trends") else {}
    tw = view.trends.get("world", {}) if hasattr(view, "trends") else {}
    mom = [float(tp.get(f"{c}_vs_t{lag}", 0.0) or 0.0) * 5.0
           for lag in (3, 12) for c in COMMODITIES]
    mine = [
        float(tm.get("gdp_vs_t12", 0.0) or 0.0) * 5.0,
        float(tm.get("unemployment_vs_t12", 0.0) or 0.0),
        float(tm.get("debt_gdp_vs_t12", 0.0) or 0.0) * 5.0,
        float(tm.get("fx_vs_t12", 0.0) or 0.0) * 5.0,
        float(tw.get("world_gdp_vs_t12", 0.0) or 0.0) * 5.0,
    ]
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
        *mom,
        *mine,
        # 思想・ドクトリン: 同じ重みでも「自分がどんな政府か」で戦術を変えられる
        float(me.get("doctrine_risk", 0.5)),
        float(me.get("doctrine_militarism", 0.3)),
        float(me.get("doctrine_revisionism", 0.2)),
        float(me.get("doctrine_vengeance", 0.3)),
        float(me.get("doctrine_treaty_fidelity", 0.7)),
        1.0 if me.get("nuclear_posture") == "counterforce" else 0.0,
        1.0 if me.get("nuclear_posture") == "nfu" else 0.0,
    ], dtype=np.float32)
    return np.clip(obs, -5.0, 5.0)


class ExternalPolicy:
    """Policy slot whose decision is injected from outside (the RL loop)."""

    def __init__(self) -> None:
        self.pending = Decisions(rationale="rl tactical")

    def decide(self, view: NationView) -> Decisions:
        return self.pending


BUDGET_LEVELS = [0.05, 0.15, 0.30, 0.45, 0.60]   # 各軸5水準の微調整
BUDGET_AXES = ("military", "welfare", "stockpile", "subsidy")


def action_to_decisions(action: dict) -> Decisions:
    from .nets import BUDGET_PRESETS, POSTURES
    if "budget_levels" in action:
        # 細粒度行動: 4軸それぞれの水準を正規化して予算に
        vals = {ax: BUDGET_LEVELS[lv] for ax, lv in zip(BUDGET_AXES, action["budget_levels"])}
        tot = sum(vals.values()) or 1.0
        budget = {ax: round(v / tot, 3) for ax, v in vals.items()}
    else:
        budget = dict(BUDGET_PRESETS[action["budget_idx"]])
    return Decisions(
        budget=budget,
        diplomacy=[],
        military_posture=POSTURES[action["posture_idx"]],
        rationing=bool(action["rationing"]),
        propaganda=bool(action["propaganda"]),
        rationale="RL tactical allocation",
    )


def reward_snapshot(eng: Engine, nation_id: str) -> dict:
    nat = eng.nations[nation_id]
    return {
        "log_gdp": float(np.log(max(nat.gdp, 0.1))),
        "stability": nat.stability,
        "approval": nat.approval,
        "military": nat.military,
        "war": len(nat.at_war_with),
        "collapsed": nat.collapsed,
        "min_stock": min(nat.stocks.values()),
    }


def tick_reward(eng: Engine, nation_id: str, prev: dict, default_penalty: float = 0.0) -> float:
    """Per-tick shaping reward for one nation (shared by single- and multi-agent).

    default_penalty > 0 additionally punishes this nation's sovereign default,
    letting the god/experimenter trade growth-seeking against debt discipline.
    成長項は月次換算に正規化する: 時計の圧縮率(1tick=1時間でも1ヶ月でも)
    によらず学習シグナルのスケールを保つ。
    """
    cur = reward_snapshot(eng, nation_id)
    fm = max(getattr(eng, "_fm", lambda: 1.0)(), 1e-9)
    r = 0.0
    r += 20.0 * (cur["log_gdp"] - prev["log_gdp"]) / fm
    r += 0.30 * (cur["stability"] - prev["stability"])
    r += 0.10 * (cur["approval"] - prev["approval"])
    r -= 0.40 * cur["war"]
    # 報酬の異質性: 軍事偏重の政府は軍備そのものを効用とする（思想の反映）
    r += 0.02 * eng.nations[nation_id].doctrine_militarism * (cur["military"] - prev["military"])
    # 統治の質: 安定度の水準報酬（月次換算）。Δ項だけだと崩壊→回復の
    # 往復が打ち消し合い、「生き続ける」ことへの勾配が消える。
    # GRUの運用実測で成長偏重が崩壊波を生んだため水準報酬を強化した。
    r += 0.15 * cur["stability"] * fm
    # shortage events hitting this nation this tick (dominant penalty:
    # rationing/hoarding only matter insofar as they prevent these)
    for rec in eng.event_log.records:
        if rec.tick != eng.tick_no:
            continue
        if rec.type == "shortage" and (rec.actor == nation_id or nation_id in rec.targets):
            r -= 2.0
        elif rec.type == "sovereign_default" and rec.actor == nation_id:
            r -= default_penalty
    if cur["collapsed"] and not prev["collapsed"]:
        r -= 20.0
    return float(r)


class NationEnv:
    """gym-style single-agent env over the engine (1 tick = 1 step)."""

    def __init__(self, preset: str, nation_id: str, seed: int = 0,
                 horizon: int = 24, scenario: Optional[Scenario] = None,
                 default_penalty: float = 0.0):
        self.preset = preset
        self.nation_id = nation_id
        self.seed = seed
        self.horizon = horizon
        self.scenario = scenario or Scenario()
        self.default_penalty = default_penalty
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
        self._prev = reward_snapshot(self.eng, self.nation_id)
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
        reward = tick_reward(eng, self.nation_id, self._prev,
                             default_penalty=self.default_penalty)
        nat = eng.nations[self.nation_id]
        done = eng.tick_no >= self.horizon - 1 or nat.collapsed
        info = {"tick": eng.tick_no, "collapsed": nat.collapsed}
        self._prev = reward_snapshot(eng, self.nation_id)
        return obs, reward, done, info


class SelfPlayEnv:
    """Multi-agent env: several learner nations in ONE engine (self-play).

    Every learner acts each tick from its own observation; the remaining
    nations run the heuristic. step() takes {nation_id: action} and returns
    per-nation observation/reward dicts — each net trains against the others,
    so tactics co-evolve instead of overfitting to fixed heuristic opponents.
    """

    def __init__(self, preset: str, nation_ids: list[str], seed: int = 0,
                 horizon: int = 24, scenario: Optional[Scenario] = None,
                 default_penalty: float = 0.0):
        self.preset = preset
        self.nation_ids = list(nation_ids)
        self.seed = seed
        self.horizon = horizon
        self.scenario = scenario or Scenario()
        self.default_penalty = default_penalty
        self._ep = 0
        self.learners = {nid: ExternalPolicy() for nid in self.nation_ids}
        self.eng: Optional[Engine] = None
        self._prev: dict = {}

    def _build(self) -> Engine:
        spec = load_preset(self.preset)
        policies = {ns.id: HeuristicPolicy() for ns in spec.nations}
        for nid in self.nation_ids:
            policies[nid] = self.learners[nid]
        eng = Engine(spec, policies, seed=self.seed * 100003 + self._ep, out_dir=None)
        return eng

    # ------------------------------------------------------------------ api
    def reset(self) -> dict[str, np.ndarray]:
        self._ep += 1
        self.eng = self._build()
        self._prev = {nid: reward_snapshot(self.eng, nid) for nid in self.nation_ids}
        return {nid: obs_from_view(self.eng.nation_view(nid)) for nid in self.nation_ids}

    def step(self, actions: dict[str, dict]):
        eng = self.eng
        for nid, act in actions.items():
            self.learners[nid].pending = action_to_decisions(act)
        eng.tick_no = eng.snapshots[-1]["tick"] + 1 if eng.snapshots else 0
        for iv in self.scenario.interventions:
            if iv.tick == eng.tick_no:
                eng.apply_intervention(iv)
        eng.step()
        obs = {nid: obs_from_view(eng.nation_view(nid)) for nid in self.nation_ids}
        rewards = {}
        for nid in self.nation_ids:
            rewards[nid] = tick_reward(eng, nid, self._prev[nid],
                                       default_penalty=self.default_penalty)
            self._prev[nid] = reward_snapshot(eng, nid)
        alive = [nid for nid in self.nation_ids if not eng.nations[nid].collapsed]
        done = eng.tick_no >= self.horizon - 1 or not alive
        info = {"tick": eng.tick_no, "alive": alive}
        return obs, rewards, done, info
