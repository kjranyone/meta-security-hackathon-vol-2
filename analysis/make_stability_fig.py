"""危機安定性実験の図（箱ひげ図）: policy x deterrence -> wars, first tick."""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "out"
plt.rcParams.update({"font.size": 10, "axes.facecolor": "#11151c", "figure.facecolor": "#0d1117",
                     "axes.edgecolor": "#30363d", "axes.labelcolor": "#e6edf3",
                     "xtick.color": "#8b949e", "ytick.color": "#8b949e", "text.color": "#e6edf3",
                     "savefig.facecolor": "#0d1117"})
JP = {"family": ["Hiragino Sans", "Noto Sans CJK JP", "Yu Gothic", "sans-serif"]}

files = sorted(OUT.glob("stability_*.csv"))
if not files:
    sys.exit("no stability CSVs")
data = defaultdict(list)
for f in files:
    for r in csv.DictReader(open(f)):
        data[(r["policy"], r["deterrence"])].append(r)

ORDER = [("heuristic", "none"), ("heuristic", "status"), ("heuristic", "expanded"),
         ("rl", "none"), ("rl", "status"), ("rl", "expanded"), ("llm", "status")]
labels = {"heuristic": "ルールAI", "rl": "学習AI", "llm": "思考AI",
          "none": "核なし", "status": "現状(5カ国)", "expanded": "拡散(8カ国)"}
keys = [k for k in ORDER if k in data]
xs = [f"{labels[p]}\n{labels[d]}" for p, d in keys]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
wars = [[int(r["wars_started"]) for r in data[k]] for k in keys]
ax1.boxplot(wars, tick_labels=xs, patch_artist=True,
            boxprops=dict(facecolor="#21262d"), medianprops=dict(color="#f0883e"))
for i, w in enumerate(wars, 1):
    ax1.scatter([i] * len(w), w, color="#58a6ff", s=14, zorder=3)
ax1.set_ylabel("戦争開始数（24tick）", **JP)
ax1.set_title("Q2: 抑止構成が戦争数を変える", **JP)
ax1.grid(color="#21262d", axis="y")

firsts = [[int(r["first_war_tick"]) for r in data[k] if int(r["first_war_tick"]) >= 0] for k in keys]
ax2.boxplot(firsts, tick_labels=xs, patch_artist=True,
            boxprops=dict(facecolor="#21262d"), medianprops=dict(color="#f0883e"))
for i, w in enumerate(firsts, 1):
    ax2.scatter([i] * len(w), w, color="#58a6ff", s=14, zorder=3)
ax2.set_ylabel("初回開戦tick（早い=危険）", **JP)
ax2.set_title("Q1: AI層と抑止のエスカレーション速度", **JP)
ax2.grid(color="#21262d", axis="y")

fig.tight_layout()
out = OUT / "crisis_stability.png"
fig.savefig(out, dpi=150)
print(f"wrote {out}")
