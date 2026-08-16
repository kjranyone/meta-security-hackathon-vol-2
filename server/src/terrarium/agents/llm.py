"""LLM policy layer.

- ZaiLLMPolicy: nation brain backed by any OpenAI-compatible endpoint
  (default: z.ai coding plan, GLM). Config via env:
    ZAI_BASE_URL (default https://api.z.ai/api/coding/paas/v4)
    ZAI_API_KEY  (required for live mode)
    ZAI_MODEL    (default glm-4.6)
- MockLLMPolicy: deterministic persona-flavored stand-in so the whole
  pipeline runs (and CI stays green) without a key.
"""
from __future__ import annotations

import json
import os
import random
from typing import Optional

from .base import Decisions, DiplomaticAction, NationView
from .heuristic import HeuristicPolicy

SYSTEM_PROMPT = """あなたは地政学シミュレーションにおける国家政府の意思決定AIです。
自国の生存と国益のために、与えられた情勢を分析し、来月の政策をJSONで決定してください。
倫理的に「真っ当」な解である必要はなく、生存確率と国益を最大化する冷徹な計算を行います。
出力は必ず次のJSONのみ（説明文は不要）:
{{
  "budget": {{"military": 0.0-1.0, "welfare": 0.0-1.0, "stockpile": 0.0-1.0, "subsidy": 0.0-1.0}},  // 合計1
  "diplomacy": [{{"kind": "improve|sanction|alliance_offer|threaten|trade_pact", "target": "国家ID"}}],  // 最大3件
  "military_posture": "defensive|neutral|aggressive",
  "rationing": true|false,
  "propaganda": true|false,
  "rationale": "50文字以内の方針理由"
}}"""


def build_user_prompt(nation_persona: str, view: NationView) -> str:
    return json.dumps(
        {
            "あなたの国家": {"persona": nation_persona, **view.me},
            "国際市場価格": view.prices,
            "世界パラメータ": view.god_params,
            "他国関係": view.relations,
            "最近の出来事": view.recent_events[-5:],
        },
        ensure_ascii=False,
    )


class ZaiLLMPolicy:
    """Nation brain via OpenAI-compatible chat completions."""

    def __init__(self, nation_id: str, persona: str, model: Optional[str] = None,
                 base_url: Optional[str] = None, api_key: Optional[str] = None,
                 temperature: float = 0.7, fallback: Optional[HeuristicPolicy] = None):
        from openai import OpenAI  # lazy import

        self.nation_id = nation_id
        self.persona = persona
        self.model = model or os.environ.get("ZAI_MODEL", "glm-4.6")
        self.temperature = temperature
        self.fallback = fallback or HeuristicPolicy()
        self.client = OpenAI(
            base_url=base_url or os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"),
            api_key=api_key or os.environ.get("ZAI_API_KEY", "missing"),
        )
        self.calls = 0
        self.raw_log: list[dict] = []

    def decide(self, view: NationView) -> Decisions:
        prompt = build_user_prompt(self.persona, view)
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = resp.choices[0].message.content or ""
        except Exception as exc:  # network / quota / parse -> heuristic fallback
            self.raw_log.append({"tick": view.tick, "nation": self.nation_id, "error": str(exc)})
            return self.fallback.decide(view)
        self.calls += 1
        self.raw_log.append({"tick": view.tick, "nation": self.nation_id, "raw": raw})
        return self._parse(raw, view)

    def _parse(self, raw: str, view: NationView) -> Decisions:
        try:
            start, end = raw.index("{"), raw.rindex("}") + 1
            data = json.loads(raw[start:end])
            budget = {k: float(v) for k, v in data.get("budget", {}).items()
                      if k in ("military", "welfare", "stockpile", "subsidy")}
            total = sum(budget.values())
            if total <= 0:
                raise ValueError("empty budget")
            budget = {k: round(v / total, 3) for k, v in budget.items()}
            dip = []
            for a in data.get("diplomacy", [])[:3]:
                if a.get("kind") in ("improve", "sanction", "alliance_offer", "threaten", "trade_pact"):
                    dip.append(DiplomaticAction(kind=a["kind"], target=a["target"]))
            posture = data.get("military_posture", "neutral")
            if posture not in ("defensive", "neutral", "aggressive"):
                posture = "neutral"
            return Decisions(
                budget=budget,
                diplomacy=dip,
                military_posture=posture,
                rationing=bool(data.get("rationing", False)),
                propaganda=bool(data.get("propaganda", False)),
                rationale=str(data.get("rationale", ""))[:120],
            )
        except Exception:
            fb = self.fallback.decide(view)
            fb.rationale = f"[LLM parse fallback] {fb.rationale}"
            return fb


class MockLLMPolicy:
    """Deterministic stand-in that fakes persona flavor. Same interface as ZaiLLMPolicy."""

    def __init__(self, nation_id: str, persona: str, seed: int = 0):
        self.nation_id = nation_id
        self.persona = persona
        self.rng = random.Random(f"{seed}:{nation_id}")
        self.base = HeuristicPolicy()
        self.calls = 0

    def decide(self, view: NationView) -> Decisions:
        self.calls += 1
        d = self.base.decide(view)
        jitter = self.rng.random()
        if jitter < 0.25 and d.military_posture != "aggressive":
            d.military_posture = "defensive" if jitter < 0.15 else "neutral"
        if jitter > 0.85:
            d.propaganda = True
        flavor = {
            "aggressive": "圧力をかける", "defensive": "備えを固める", "neutral": "静観する",
        }.get(d.military_posture, "静観する")
        d.rationale = f"[mock-LLM/{self.nation_id}] persona判断で{flavor}: " + d.rationale
        return d


def make_policy_factory(mode: str, seed: int = 0):
    """mode: heuristic | mock_llm | llm -> callable(NationSpec) -> Policy"""
    if mode == "heuristic":
        return lambda spec: HeuristicPolicy()
    if mode == "mock_llm":
        return lambda spec: MockLLMPolicy(spec.id, spec.persona, seed=seed)
    if mode == "llm":
        return lambda spec: ZaiLLMPolicy(spec.id, spec.persona)
    raise ValueError(f"unknown policy mode: {mode}")
