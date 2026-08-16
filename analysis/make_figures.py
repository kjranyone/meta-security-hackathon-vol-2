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

REPO = Path(__file__).resolve().parents[1]
LOGS = REPO / "server" / "logs"
OUT = Path(__file__).resolve().parent / "out"
JP = {"family": ["Hiragino Sans", "Noto Sans CJK JP", "Yu Gothic", "sans-serif"]}
plt.rcParams.update({"font.size": 10, "axes.facecolor": "#11151c", "figure.facecolor": "#0d1117",
                     "axes.edgecolor": "#30363d", "axes.labelcolor": "#e6edf3",
                     "xtick.color": "#8b949e", "ytick.color": "#8b949e", "text.color": "#e6edf3",
                     "savefig.facecolor": "#0d1117"})

EVENT_COLOR = {"god_intervention": "#a371f7", "trade_throttled": "#e3b341", "price_spike": "#e3b341",
               "shortage": "#db6d28", "sovereign_default": "#ff6b35", "credibility_hit": "#ffa657",
               "war_start": "#f85149", "collapse": "#d29922", "sanction": "#d29922",
               "disinfo": "#f778ba", "tech_emergence": "#3fdeff", "tech_adopted": "#2f9c99",
               "policy_shift": "#8b949e", "threat": "#d29922", "alliance_formed": "#3fb950"}


def load_events(run: str) -> list[dict]:
    path = LOGS / run / "events.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_series(run: str) -> list[dict]:
    import csv

    with (LOGS / run / "series.csv").open() as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- cascade graph
def cascade_graph(run: str, max_nodes: int = 120) -> Path | None:
    events = load_events(run)
    by_id = {e["id"]: e for e in events}
    roots = [e for e in events if e["type"] in ("god_intervention", "tech_emergence") and not e["parents"]]
    if not roots:
        roots = [e for e in events if not e["parents"]]
    # BFS downstream from roots, capped
    nodes, edges, depth = {}, [], {}
    frontier = [(r["id"], 0) for r in roots]
    while frontier and len(nodes) < max_nodes:
        eid, d = frontier.pop(0)
        if eid in nodes:
            continue
        e = by_id.get(eid)
        if e is None:
            continue
        nodes[eid] = e
        depth[eid] = d
        for child in events:
            if eid in child["parents"] and child["id"] not in nodes:
                edges.append((eid, child["id"]))
                frontier.append((child["id"], d + 1))
    if len(nodes) < 3:
        return None
    # layout: depth -> x, spread -> y
    by_depth = defaultdict(list)
    for eid, d in depth.items():
        by_depth[d].append(eid)
    pos = {}
    for d, ids in by_depth.items():
        for i, eid in enumerate(ids):
            pos[eid] = (d, (i - (len(ids) - 1) / 2) * max(1.0, 24 / max(1, len(ids))))

    fig, ax = plt.subplots(figsize=(14, 9))
    for a, b in edges:
        if a in pos and b in pos:
            xa, ya = pos[a]
            xb, yb = pos[b]
            ax.annotate("", xy=(xb, yb), xytext=(xa, ya),
                        arrowprops=dict(arrowstyle="-", color="#30363d", lw=0.6, alpha=0.7))
    for eid, e in nodes.items():
        x, y = pos[eid]
        c = EVENT_COLOR.get(e["type"], "#8b949e")
        ax.scatter([x], [y], s=42, color=c, zorder=3, edgecolors="#0d1117", linewidths=0.5)
    for eid, e in nodes.items():
        x, y = pos[eid]
        # label only high-signal event types to avoid clutter
        if e["type"] in ("god_intervention", "sovereign_default", "war_start", "collapse",
                         "tech_emergence", "disinfo", "alliance_formed"):
            label = e["text"][:24]
            ax.annotate(label, (x, y), fontsize=5.5, color="#c9d1d9",
                        xytext=(3, 3), textcoords="offset points")
    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=7, label=t)
               for t, c in list(EVENT_COLOR.items())[:10]]
    ax.legend(handles=handles, loc="upper right", fontsize=7, facecolor="#161b22", labelcolor="#e6edf3")
    ax.set_title(f"介入のカスケードグラフ — {run}（因果親リンクから再構成）", fontdict=JP)
    ax.set_xlabel("因果の深さ（神/創発 → 下流）")
    ax.set_xticks(sorted(by_depth.keys()))
    ax.margins(0.05)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="earth_baseline")
    ap.add_argument("--runs", nargs="*", default=None, help="treatment runs (default: all earth_* except baseline)")
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    all_runs = sorted(p.name for p in LOGS.iterdir() if p.is_dir()) if LOGS.exists() else []
    treats = args.runs or [r for r in all_runs if r != args.baseline and r.startswith("earth")]
    made = []
    for r in [args.baseline] + treats:
        if (LOGS / r / "events.jsonl").exists():
            f = cascade_graph(r)
            if f:
                made.append(f)
            f = cascade_bar(r)
            if f:
                made.append(f)
    for r in treats:
        if (LOGS / r / "series.csv").exists():
            f = ab_divergence(args.baseline, r)
            if f:
                made.append(f)
    f = sensitivity(args.baseline, treats)
    if f:
        made.append(f)
    print(json.dumps([str(m) for m in made], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
