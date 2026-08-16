"""Smoke test for the z.ai (OpenAI-compatible) endpoint.

Usage:
  ZAI_API_KEY=... uv run python scripts/smoke_test_llm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from terrarium.agents.base import NationView  # noqa: E402
from terrarium.agents.llm import ZaiLLMPolicy  # noqa: E402
from terrarium.util.env import load_env  # noqa: E402


def main() -> int:
    load_env(Path(__file__).resolve().parents[1] / ".env")
    import os

    if not os.environ.get("ZAI_API_KEY"):
        print("ZAI_API_KEY not set. Put it in server/.env as: ZAI_API_KEY=sk-...")
        return 1

    view = NationView(
        tick=1,
        me={
            "name": "Voltania", "gdp": 5.2, "inflation": 0.02, "stability": 72,
            "stocks": {"energy": 1.2, "food": 3.0, "chips": 6.0},
            "aggression": 0.2, "paranoia": 0.35, "at_war_with": [],
        },
        prices={"energy": 1.3, "food": 1.0, "chips": 1.0},
        god_params={"trade_efficiency": 1.0, "ai_aggression": 1.0},
        relations={"PTR": {"trust": 10.0, "alliance": False, "war": False, "sanction": False}},
        market_news=["energy price 1.30"],
        recent_events=["Petrova が海峡で軍事演習"],
    )
    policy = ZaiLLMPolicy("VLT", "技術立島国。半導体ファブを握るがエネルギーは海外依存。")
    d = policy.decide(view)
    print("decisions:", d.model_dump_json(indent=2))
    if policy.calls == 0:
        print("LLM call failed (fell back to heuristic). Check ZAI_BASE_URL / ZAI_MODEL / key.")
        print("raw_log:", policy.raw_log)
        return 2
    print("OK - live LLM decision obtained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
