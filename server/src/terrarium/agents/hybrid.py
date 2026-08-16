"""Hybrid strategy AI: LLM strategy x RL tactics.

Division of labour (the core architecture claim of this project):
  - LLM (strategy layer): diplomacy, military posture, rationing/propaganda
    judgement, natural-language rationale -- slow, semantic, persona-driven
  - RL (tactical layer): monthly budget allocation learned through
    thousands of simulated months -- fast, optimized, no language needed
  - rules (world layer): market/physics resolution in the engine
"""
from __future__ import annotations

from .base import Decisions, NationView
from .rl_policy import RLPolicy


class HybridPolicy:
    def __init__(self, llm_policy, rl_policy: RLPolicy):
        self.llm = llm_policy
        self.rl = rl_policy

    def decide(self, view: NationView) -> Decisions:
        try:
            strategy = self.llm.decide(view)
        except Exception:
            strategy = None
        tactics = self.rl.decide(view)
        if strategy is None:
            tactics.rationale = "[llm-failed] " + tactics.rationale
            return tactics
        tactics.diplomacy = strategy.diplomacy
        tactics.military_posture = strategy.military_posture
        tactics.rationing = strategy.rationing or tactics.rationing
        tactics.propaganda = strategy.propaganda
        tactics.rationale = (
            f"[LLM戦略: {strategy.rationale}] × [RL戦術: 予算{max(tactics.budget, key=tactics.budget.get)}]"
        )[:200]
        return tactics
