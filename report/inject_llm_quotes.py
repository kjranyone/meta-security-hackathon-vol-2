#!/usr/bin/env python3
"""Inject LLM nation-AI rationale quotes into report/slides.html.

Reads policy_shift events from the full-LLM run log (server/logs/
earth_llm_hormuz/events.jsonl), picks high-signal rationales across
different nations and ticks, and fills the #llm_quotes box. No-op when
the log is absent, so the slides build stays reproducible at any stage.

Usage: python3 report/inject_llm_quotes.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "server" / "logs" / "earth_llm_hormuz" / "events.jsonl"
SLIDES = Path(__file__).resolve().parent / "slides.html"

MAX_QUOTES = 6


def pick_quotes() -> list[dict]:
    if not RUN.exists():
        return []
    evs = [json.loads(l) for l in RUN.read_text(encoding="utf-8").splitlines() if l.strip()]
    # "doctrine:" marks the heuristic-fallback rationale, not LLM thinking
    shifts = [e for e in evs if e["type"] == "policy_shift" and len(e["text"]) > 55
              and "doctrine:" not in e["text"]]
    # per nation keep the richest rationale (longest), then round-robin nations
    by_actor: dict[str, list[dict]] = {}
    for e in sorted(shifts, key=lambda x: -len(x["text"])):
        by_actor.setdefault(e["actor"], []).append(e)
    picked, actors = [], sorted(by_actor)
    round_no = 0
    while len(picked) < MAX_QUOTES and any(by_actor[a] for a in actors):
        for a in actors:
            if len(picked) >= MAX_QUOTES:
                break
            if round_no < len(by_actor[a]):
                picked.append(by_actor[a][round_no])
        round_no += 1
    return picked


def main() -> int:
    quotes = pick_quotes()
    html = SLIDES.read_text(encoding="utf-8")
    if not quotes:
        print("no LLM run log yet; slides unchanged")
        return 0
    nation = {"JPN": "日本", "USA": "米国", "CHN": "中国", "EUR": "EU", "SAU": "サウジ",
              "RUS": "ロシア", "IND": "インド", "EGY": "エジプト", "TWN": "台湾",
              "KOR": "韓国", "IRN": "イラン", "TUR": "トルコ", "IDN": "インドネシア",
              "AUS": "豪州", "CAN": "カナダ", "BRA": "ブラジル"}
    items = []
    for e in quotes:
        text = e["text"]
        # strip "<name>: " prefix from the event text to get the rationale
        rationale = re.sub(r"^[^:]+:\s*", "", text)
        actor = nation.get(e["actor"], e["actor"])
        items.append(
            f'<p style="margin:6px 0;"><b>t{e["tick"]} {actor}</b>'
            f'<span class="sub">（{e["data"].get("posture", "")}）</span><br>'
            f"{rationale[:220]}…</p>"
        )
    block = "\n".join(items)
    new_html = re.sub(
        r'(<div id="llm_quotes" class="box"[^>]*>).*?(</div>)',
        lambda m: m.group(1) + block + m.group(2),
        html, flags=re.S)
    if new_html != html:
        SLIDES.write_text(new_html, encoding="utf-8")
        print(f"injected {len(quotes)} quotes into {SLIDES}")
    else:
        print("quote box not found or unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
