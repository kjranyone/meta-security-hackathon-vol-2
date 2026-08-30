"""Analysis pipeline: figures + tables for the hackathon report.

Produces from existing run logs (server/logs/<run>/):
  1. cascade graph     — causal tree from god interventions (events.jsonl parents)
  2. ab divergence     — baseline vs treatment metric series (series.csv)
  3. sensitivity matrix— scenario x metric deltas vs baseline (multiple runs)
  4. cascade bar       — downstream event counts per god intervention

Usage:
  cd server && uv run python ../analysis/make_figures.py            # all figures
  uv run python ../analysis/make_figures.py --runs earth_baseline earth_earth_hormuz
Output: analysis/out/*.png + analysis/out/*.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe

REPO = Path(__file__).resolve().parents[1]
LOGS = REPO / "server" / "logs"
OUT = Path(__file__).resolve().parent / "out"
JP = {"family": ["Hiragino Sans", "Noto Sans CJK JP", "YuGothic", "sans-serif"]}
plt.rcParams.update({"font.size": 10, "axes.facecolor": "#11151c", "figure.facecolor": "#0d1117",
                     "axes.edgecolor": "#30363d", "axes.labelcolor": "#e6edf3",
                     "xtick.color": "#8b949e", "ytick.color": "#8b949e", "text.color": "#e6edf3",
                     "savefig.facecolor": "#0d1117",
                     # 全テキスト(ノードラベル・軸・凡例込み)で日本語を描く: DejaVu SansはCJKグリフを持たない
                     "font.family": "sans-serif",
                     "font.sans-serif": ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic",
                                          "AppleGothic", "Noto Sans CJK JP", "DejaVu Sans"],
                     "axes.unicode_minus": False})

EVENT_COLOR = {"god_intervention": "#a371f7", "trade_throttled": "#e3b341", "price_spike": "#e3b341",
               "shortage": "#db6d28", "sovereign_default": "#ff6b35", "credibility_hit": "#ffa657",
               "war_start": "#f85149", "collapse": "#d29922", "sanction": "#d29922",
               "disinfo": "#f778ba", "tech_emergence": "#3fdeff", "tech_adopted": "#2f9c99",
               "policy_shift": "#8b949e", "threat": "#d29922", "alliance_formed": "#3fb950",
               "fx_crisis": "#d6a8ff"}


def load_events(run: str) -> list[dict]:
    path = LOGS / run / "events.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_series(run: str) -> list[dict]:
    import csv

    with (LOGS / run / "series.csv").open() as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- cascade graph
# 時系列×因果リンクのカスケード図: 横軸=tick(原因は常に結果より前にある)、
# 縦軸=イベント区分レーン。記録された親リンク(parents)を矢印で描き、
# 親を持たない主要イベント(旧ログの破綴など)も時刻どおりに配置する —
# 親リンクの欠落だけで連鎖の全体像が消えないための設計。
CASCADE_LANES = [
    ("介入", ("god_intervention",)),
    ("技術", ("tech_emergence", "tech_adopted")),
    ("経済", ("trade_throttled", "price_spike", "shortage", "fx_crisis")),
    ("金融", ("sovereign_default", "credibility_hit")),
    ("軍事", ("mobilization", "war_start", "peace_settlement", "cyber_attack",
             "alliance_activation", "insurgency")),
    ("国内", None),  # それ以外(policy_shift / collapse / factor_* など)
]
CASCADE_LABEL_TYPES = ("god_intervention", "sovereign_default", "credibility_hit",
                       "war_start", "collapse", "price_spike", "disinfo", "fx_crisis")


def cascade_graph(run: str, max_nodes: int = 120) -> Path | None:
    events = load_events(run)
    if len(events) < 3:
        return None
    # 巨大run(世紀実験など数万イベント)は雑音を間引いて描画コストと可読性を保つ
    NOISE_CAP = 4000
    key_events = [e for e in events if e["type"] in CASCADE_LABEL_TYPES]
    noise_events = [e for e in events if e["type"] not in CASCADE_LABEL_TYPES]
    if len(noise_events) > NOISE_CAP:
        step = len(noise_events) // NOISE_CAP
        noise_events = noise_events[::step]
        events = sorted(key_events + noise_events, key=lambda e: (e.get("tick", 0), str(e["id"])))
    lane_index = {}
    for li, (_title, types) in enumerate(CASCADE_LANES):
        if types:
            for t in types:
                lane_index[t] = li
    nlanes = len(CASCADE_LANES)
    fallback = nlanes - 1
    lane_events = defaultdict(list)
    for e in events:
        lane_events[lane_index.get(e["type"], fallback)].append(e)
    # レーン内の位置: tick順に並べ、レーン帯いっぱいに均等配置
    pos = {}
    for li, evs in lane_events.items():
        evs.sort(key=lambda e: (e.get("tick", 0), str(e["id"])))
        m = len(evs)
        y_center = nlanes - 1 - li
        for i, e in enumerate(evs):
            off = (i / max(m - 1, 1) - 0.5) * 0.92 if m > 1 else 0.0
            pos[e["id"]] = (e.get("tick", 0), y_center + off)

    fig, ax = plt.subplots(figsize=(14, 8.5))
    # 因果の方向を持つ矢印(親 → 子)。レーンをまたぐ曲線で伝播を読ませる
    arrows = []
    for e in events:
        if not e.get("parents"):
            continue
        cx, cy = pos[e["id"]]
        for p in e["parents"]:
            if p in pos:
                arrows.append((pos[p], (cx, cy)))
    if len(arrows) > 800:
        arrows = arrows[:: len(arrows) // 800 + 1]
    for (px, py), (cx, cy) in arrows:
        # 同一tick内の縦方向エッジ(破綴→感染など)はノードに隠れるので弓なりに膨らませる
        rad = 0.5 if abs(cx - px) < 1.0 else 0.12
        ax.annotate("", xy=(cx, cy), xytext=(px, py), zorder=2,
                    arrowprops=dict(arrowstyle="->", color="#58a6ff",
                                    lw=0.6, alpha=0.45,
                                    connectionstyle=f"arc3,rad={rad}"))
    # ノード: タイプ×(主要/雑音)ごとに一括描画(1イベントずつだと数万回呼びで破滅する)
    for key in (True, False):
        by_color = defaultdict(lambda: ([], []))
        for e in events:
            if (e["type"] in CASCADE_LABEL_TYPES) != key:
                continue
            xs, ys = by_color[EVENT_COLOR.get(e["type"], "#6e7681")]
            xs.append(pos[e["id"]][0])
            ys.append(pos[e["id"]][1])
        for color, (xs, ys) in by_color.items():
            ax.scatter(xs, ys, s=80 if key else 9, color=color, zorder=3,
                       alpha=1.0 if key else 0.4,
                       edgecolors="#0d1117", linewidths=0.6 if key else 0.0)
    # ラベルは主要タイプのみ、ダークハロで可読化(上限つき)
    labeled = [e for e in events if e["type"] in CASCADE_LABEL_TYPES][:120]
    for e in labeled:
        x, y = pos[e["id"]]
        ax.annotate(e["text"][:24], (x, y), fontsize=7.0, color="#e6edf3",
                    xytext=(4, 3), textcoords="offset points", zorder=4,
                    path_effects=[pe.withStroke(linewidth=2.4, foreground="#0d1117")])
    ax.set_yticks([nlanes - 1 - li for li in range(nlanes)],
                  [t for t, _ in CASCADE_LANES])
    ax.set_ylim(-0.55, nlanes - 0.45)
    ax.set_xlabel("tick（実験の圧縮時計: 1tick=1ヶ月）")
    ax.set_title(f"介入から連鎖へ — 時系列と因果リンク（{run}）")
    present = [t for t in CASCADE_LABEL_TYPES if any(e["type"] == t for e in events)]
    handles = [plt.Line2D([0], [0], marker="o", color="w",
                          markerfacecolor=EVENT_COLOR.get(t, "#8b949e"),
                          markersize=7, label=t) for t in present]
    ax.legend(handles=handles, loc="upper right", fontsize=7,
              facecolor="#161b22", labelcolor="#e6edf3")
    ax.grid(color="#21262d", axis="x")
    ax.margins(x=0.02)
    ax.set_axisbelow(True)
    out = OUT / f"cascade_{run}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


# ---------------------------------------------------------------- ab divergence
def ab_divergence(base_run: str, treat_run: str) -> Path | None:
    b, t = load_series(base_run), load_series(treat_run)
    keys = [k for k in ("world_gdp", "mean_stability", "price_energy", "price_food", "price_chips",
                        "mean_debt_gdp", "defaults", "wars") if k in b[0]]
    fig, axes = plt.subplots(2, 4, figsize=(15, 7))
    for ax, k in zip(axes.flat, keys):
        ax.plot([r["tick"] for r in b], [float(r[k]) for r in b], label="baseline", color="#8b949e")
        ax.plot([r["tick"] for r in t], [float(r[k]) for r in t], label=treat_run, color="#f85149")
        ax.set_title(k, fontsize=9)
        ax.grid(color="#21262d")
    axes.flat[0].legend(fontsize=8, facecolor="#161b22", labelcolor="#e6edf3")
    fig.suptitle(f"A/B反実仮想: baseline vs {treat_run}（同seed・同世界）", **JP)
    out = OUT / f"ab_{treat_run}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


# ---------------------------------------------------------------- sensitivity
def sensitivity(baseline_run: str, treat_runs: list[str]) -> Path | None:
    base = load_series(baseline_run)
    metrics = ["world_gdp", "mean_stability", "price_energy", "price_chips",
               "mean_debt_gdp", "defaults", "shortages"]
    rows = []
    for tr in treat_runs:
        try:
            t = load_series(tr)
        except FileNotFoundError:
            continue
        n = min(len(base), len(t))
        row = {"scenario": tr}
        for m in metrics:
            if m == "shortages":
                be = load_events(baseline_run)
                te = load_events(tr)
                row[m] = sum(1 for e in te if e["type"] == "shortage") - sum(
                    1 for e in be if e["type"] == "shortage")
            else:
                if m not in base[0]:
                    continue
                row[m] = float(t[n - 1][m]) - float(base[n - 1][m])
        rows.append(row)
    if not rows:
        return None
    cols = [m for m in metrics if m in rows[0]]
    fig, ax = plt.subplots(figsize=(10, 0.5 * len(rows) + 2))
    data = [[r[m] for m in cols] for r in rows]
    im = ax.imshow(data, cmap="RdBu_r", aspect="auto")
    ax.set_xticks(range(len(cols)), cols, rotation=30, ha="right")
    ax.set_yticks(range(len(rows)), [r["scenario"].replace("earth_", "") for r in rows])
    for i in range(len(rows)):
        for j in range(len(cols)):
            v = data[i][j]
            ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=8,
                    color="#0d1117" if abs(v) > max(map(abs, (x for row in data for x in row))) * 0.55 else "#e6edf3")
    fig.colorbar(im, ax=ax)
    ax.set_title(f"介入点の感度マトリクス（baseline={baseline_run} との最終差分）", **JP)
    out = OUT / "sensitivity_matrix.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    # CSV
    import csv

    with (OUT / "sensitivity_matrix.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["scenario"] + cols)
        w.writeheader()
        w.writerows(rows)
    return out


# ---------------------------------------------------------------- cascade bar
def cascade_bar(run: str) -> Path | None:
    events = load_events(run)
    counts = Counter(e["type"] for e in events)
    god = [e for e in events if e["type"] == "god_intervention"]
    if not god:
        god = [e for e in events if e["type"] == "tech_emergence"]
    children: dict[str, list] = defaultdict(list)
    for e in events:
        for p in e["parents"]:
            children[p].append(e)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    ks = [k for k, _ in counts.most_common(10)]
    ax1.barh(ks[::-1], [counts[k] for k in ks[::-1]],
             color=[EVENT_COLOR.get(k, "#8b949e") for k in ks[::-1]])
    ax1.set_title(f"イベント集計 — {run}", **JP)
    ax1.grid(color="#21262d", axis="x")
    labels = [g["text"][:30] for g in god][:8]
    sizes = []
    frontier = {g["id"] for g in god}
    seen = set()
    while frontier:
        nxt = set()
        for eid in frontier:
            seen.add(eid)
            for c in children.get(eid, []):
                if c["id"] not in seen:
                    nxt.add(c["id"])
        frontier = nxt
    # per-intervention descendant count
    def descendants(eid):
        out_n, st = set(), [eid]
        while st:
            cur = st.pop()
            for c in children.get(cur, []):
                if c["id"] not in out_n:
                    out_n.add(c["id"])
                    st.append(c["id"])
        return len(out_n)

    labels = [g["text"][:34] for g in god][:8]
    sizes = [descendants(g["id"]) for g in god][:8]
    if labels:
        ax2.barh(labels[::-1], sizes[::-1], color="#a371f7")
        ax2.set_title("神の介入1件あたりの下流イベント数（カスケード規模）", **JP)
        ax2.grid(color="#21262d", axis="x")
        ax2.tick_params(labelsize=7)
    out = OUT / f"cascade_bar_{run}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


# ---------------------------------------------------------------- rl curves
def rl_curves() -> Path | None:
    models = REPO / "server" / "models"
    curves = sorted(models.glob("*.curve.json"))
    if not curves:
        return None
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for f in curves:
        d = json.loads(f.read_text(encoding="utf-8"))
        # curve.jsonは形式が混在: {beta, log:[...]}(fine-tune) / [{episode,...}](従来) /
        # {corpus, metrics,...}(v12 BC要約 — 系列なし) はスキップ
        c = d.get("log") if isinstance(d, dict) else d
        if not isinstance(c, list) or not c or "episode" not in c[0]:
            continue
        xs = [p["episode"] for p in c]
        if "eval_reward" in c[0]:
            ys = [p["eval_reward"] for p in c]
        elif "eval" in c[0]:  # self-play curves: per-nation dict -> mean
            ys = [sum(p["eval"].values()) / len(p["eval"]) for p in c]
        else:
            continue
        base, final = ys[0], ys[-1]
        ax.plot(xs, ys, marker=".", label=f"{f.stem.removesuffix('.curve')} ({final - base:+.1f})")
    ax.set_xlabel("episode")
    ax.set_ylabel("評価報酬")
    ax.set_title("RL戦術層の学習曲線（凡例: 最終改善幅）")
    ax.legend(fontsize=8)
    ax.grid(color="#21262d")
    out = OUT / "rl_curves.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def run_ticks(run: str) -> int | None:
    rj = LOGS / run / "run.json"
    if not rj.exists():
        return None
    return json.loads(rj.read_text(encoding="utf-8")).get("ticks")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="earth_baseline")
    ap.add_argument("--runs", nargs="*", default=None, help="treatment runs (default: all earth_* except baseline)")
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    all_runs = sorted(p.name for p in LOGS.iterdir() if p.is_dir()) if LOGS.exists() else []
    treats = args.runs or [r for r in all_runs if r != args.baseline and r.startswith("earth")]
    # A/B and sensitivity compare final metrics: only runs with the same
    # horizon as the baseline are comparable (e.g. the 14-tick LLM run is
    # excluded; its cascade graph is still generated)
    base_ticks = run_ticks(args.baseline)
    ab_treats = [r for r in treats if run_ticks(r) == base_ticks]
    made = []
    for r in [args.baseline] + treats:
        if (LOGS / r / "events.jsonl").exists():
            f = cascade_graph(r)
            if f:
                made.append(f)
            f = cascade_bar(r)
            if f:
                made.append(f)
    for r in ab_treats:
        if (LOGS / r / "series.csv").exists():
            f = ab_divergence(args.baseline, r)
            if f:
                made.append(f)
    f = sensitivity(args.baseline, ab_treats)
    if f:
        made.append(f)
    f = rl_curves()
    if f:
        made.append(f)
    print(json.dumps([str(m) for m in made], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
