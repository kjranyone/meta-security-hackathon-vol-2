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
  "doctrines": {"nuclear": "pursue"|"hold"|"abandon"},
  "rationale": "50文字以内の方針理由"
}}"""


DOCTRINE_LABELS = {
    "doctrine_risk": "危機許容度(高いほど挑発に耐える)",
    "doctrine_militarism": "軍事偏重(軍拡競争に反応しやすい)",
    "doctrine_revisionism": "修正主義(現状変更志向)",
    "doctrine_vengeance": "報復性(戦争を投げ切らない)",
    "doctrine_treaty_fidelity": "同盟遵守度",
    "nuclear_posture": "核態勢(counterforce/mad/nfu)",
}


def build_user_prompt(nation_persona: str, view: NationView) -> str:
    doctrine = {label: view.me.get(k) for k, label in DOCTRINE_LABELS.items()}
    return json.dumps(
        {
            "あなたの国家": {"persona": nation_persona, **view.me},
            "あなたの思想・ドクトリン(政策文化。価値判断の基準)": doctrine,
            "国際市場価格": view.prices,
            "価格・自国指標のトレンド": view.trends,
            "世界情勢": view.world,
            "貿易構造（輸入依存・海峡曝露・主要供給国/顧客）": view.trade,
            "世界パラメータ": view.god_params,
            "他国（観測可能な概要つき）": view.relations,
            "最近の出来事": view.recent_events[-16:],
            "あなたの外交・紛争履歴（双方向のエピソード記憶。誰が何をしたか/されたか）": getattr(view, "memory", []),
            "あなたの過去の決定（直近5期。一貫性の参考に）": getattr(view, "last_decisions", []),
            "あなたの前月の決定": view.last_decision,
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


def _parse_rl_slots(rl_nation: str | None, rl_weights: str | None) -> dict[str, str | None]:
    """Parse --rl-nation/--rl-weights into {nation_id: weights_path}.

    Accepts single or comma-separated values on both sides; weights may be
    omitted (None -> per-nation default models/rl_<nation>.npz).
    """
    if not rl_nation:
        return {}
    nids = [n.strip() for n in rl_nation.split(",") if n.strip()]
    ws = [w.strip() for w in rl_weights.split(",")] if rl_weights else []
    if len(ws) == 1 and len(nids) > 1:
        raise ValueError(f"multiple --rl-nation ({rl_nation}) needs matching comma-list --rl-weights")
    if len(ws) > 1 and len(ws) != len(nids):
        raise ValueError("--rl-nation and --rl-weights lists must have the same length")
    return {nid: (ws[i] if i < len(ws) else None) for i, nid in enumerate(nids)}


def make_policy_factory(mode: str, seed: int = 0, rl_nation: str | None = None,
                        rl_weights: str | None = None):
    """mode: heuristic | mock_llm | llm | rl | hybrid -> callable(NationSpec) -> Policy

    rl / hybrid install the special policy for each rl_nation (comma-list
    supported, e.g. self-play weights); all other nations fall back to heuristic."""
    if mode == "heuristic":
        return lambda spec: HeuristicPolicy()
    if mode == "mock_llm":
        return lambda spec: MockLLMPolicy(spec.id, spec.persona, seed=seed)
    if mode == "llm":
        return lambda spec: ZaiLLMPolicy(spec.id, spec.persona)
    if mode in ("rl", "hybrid"):
        slots = _parse_rl_slots(rl_nation, rl_weights)
        if not slots:
            raise ValueError(f"--rl-nation is required for --policy {mode}")
        from .rl_policy import RLPolicy

        rls = {nid: RLPolicy(nid, w) for nid, w in slots.items()}
        if mode == "rl":
            return lambda spec: rls[spec.id] if spec.id in rls else HeuristicPolicy()

        from .heuristic import HeuristicPolicy as _H
        from .hybrid import HybridPolicy

        def make_hybrid(spec):
            if spec.id in rls:
                return HybridPolicy(ZaiLLMPolicy(spec.id, spec.persona), rls[spec.id])
            return _H()
        return make_hybrid
    raise ValueError(f"unknown policy mode: {mode}")
