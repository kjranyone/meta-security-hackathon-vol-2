"""公開リプレイのイベント文言を現行形式へ後処理で更新する。

経緯: 公開ギャラリーのリプレイ群は、RL政策のrationaleが
「RL tactical policy (models/...npz)」(デバッグ用パス露出)だった時代に
生成された。現在のエンジンは「RL戦術AI: 予算 軍事20/…」形式。再実行は
不要 — policy_shiftイベントはdataに budget/posture/rationing/propaganda を
持つため、そこから新形式の文言を**決定論的に再構成**できる。

安全条件: metrics列・prices・nations は一切変更しない(文言のみ)。
処理後にmetrics列の完全一致を検証する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GALLERY = REPO / "web" / "replays"

COMMODITY_JA = {"energy": "エネルギー", "food": "食料", "chips": "半導体",
                "minerals": "鉱物", "space": "宇宙"}
POSTURE_JA = {"defensive": "防御", "neutral": "中立", "aggressive": "攻勢"}
AXES = (("軍事", "military"), ("福祉", "welfare"), ("備蓄", "stockpile"), ("補助", "subsidy"))


def new_rationale(d: dict) -> str | None:
    b = d.get("budget") or {}
    if not b:
        return None
    tot = sum(b.values()) or 1.0
    alloc = "/".join(f"{ja}{100.0 * b.get(k, 0.0) / tot:.0f}" for ja, k in AXES)
    posture = POSTURE_JA.get(d.get("posture") or "", d.get("posture") or "?")
    opts = "".join(x for x, on in (("・配給ON", d.get("rationing")), ("・宣伝ON", d.get("propaganda"))) if on)
    return f"RL戦術AI: 予算 {alloc}・姿勢 {posture}{opts}"


def ja_commodity_text(text: str) -> str:
    for en, ja in COMMODITY_JA.items():
        text = text.replace(f" {en} ", f"{ja}が").replace(f"{en} の国際価格", f"{ja}の国際価格")
    return text


def process(path: Path) -> tuple[int, int, bool]:
    """returns (policy_shift件数, commodity置換件数, metrics一致)"""
    out_lines, metrics_before, n_pol, n_comm = [], [], 0, 0
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        if row.get("type") == "tick":
            metrics_before.append(row.get("metrics"))
            for e in row.get("events") or []:
                if e.get("type") == "policy_shift":
                    d = e.get("data") or {}
                    r = new_rationale(d)
                    if r:
                        actor = e["text"].split(":", 1)[0]
                        e["text"] = f"{actor}: {r}"
                        d["rationale"] = r
                        n_pol += 1
                for en in COMMODITY_JA:
                    if en in (e.get("text") or ""):
                        e["text"] = ja_commodity_text(e["text"])
                        n_comm += 1
                        break
        out_lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    metrics_after = [json.loads(l).get("metrics") for l in open(path, encoding="utf-8")
                     if '"type": "tick"' in l or '"type":"tick"' in l]
    ok = json.dumps(metrics_before, ensure_ascii=False) == json.dumps(metrics_after, ensure_ascii=False)
    return n_pol, n_comm, ok


def main() -> int:
    total_bad = 0
    for rp in sorted(GALLERY.glob("*/replay.jsonl")):
        n_pol, n_comm, ok = process(rp)
        status = "OK" if ok else "!!METRICS CHANGED!!"
        print(f"{rp.parent.name:32s} policy_shift更新 {n_pol:4d}  商品名更新 {n_comm:4d}  metrics一致={status}")
        if not ok:
            total_bad += 1
    return 1 if total_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
