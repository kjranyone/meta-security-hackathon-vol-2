"""Build analysis/terrarium_analysis.ipynb (nbformat) and execute it in place.

Usage: cd server && uv run python ../analysis/_make_notebook.py
"""
from __future__ import annotations

import pathlib
import sys

import nbformat as nbf

ROOT = pathlib.Path(__file__).resolve().parents[1]

md = lambda s: nbf.v4.new_markdown_cell(s)  # noqa: E731
code = lambda s: nbf.v4.new_code_cell(s)  # noqa: E731

cells = []
cells.append(md("""# Geopolitics Terrarium — 解析ノートブック

コミット済み実行ログ（`server/logs/`）のみから、提出レポートの根拠を再現する:

1. **実行ログの棚卸し** — 何が・どのseedで・どういう条件下で走ったか
2. **因果カスケード** — 神の介入1件が何件のイベント連鎖を生んだか（イベントのparentリンクをBFSで追跡）
3. **介入点×指標の感度** — どの介入点がどの指標に効くか
4. **A/B反実仮想** — 同seedでの介入あり/なしの世界GDP系列
5. **RL戦術層の学習曲線** — 単一国家学習と自己対戦学習
6. **LLM戦略層の思考ログ** — 国家AIが残した判断の理由（生ログ）

シミュレーションを再実行せずログから再現する点自体が、本作品の**再現性設計**
（イベントソーシング＋決定論エンジン）のデモンストレーションになっている。"""))

cells.append(code("""import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path.cwd().parent if Path.cwd().name == "analysis" else Path.cwd()
LOGS = ROOT / "server" / "logs"
MODELS = ROOT / "server" / "models"
OUT = ROOT / "analysis" / "out"
plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.3})
print("committed runs:", sorted(p.name for p in LOGS.iterdir() if p.is_dir()))"""))

cells.append(md("""## 1. 実行ログの棚卸し"""))
cells.append(code("""rows = []
for d in sorted(LOGS.iterdir()):
    rj = d / "run.json"
    if not rj.exists():
        continue
    m = json.loads(rj.read_text())
    fm = m["final_metrics"]
    rows.append({
        "run": d.name, "seed": m["seed"], "ticks": m["ticks"],
        "final_gdp": fm["world_gdp"], "defaults": fm["defaults"],
        "wars": fm["wars"], "price_energy": fm["price_energy"],
        "price_chips": fm["price_chips"],
        "shortages": m.get("event_counts", {}).get("shortage", 0),
    })
df_runs = pd.DataFrame(rows).set_index("run")
df_runs.round(2)"""))

cells.append(md("""## 2. 因果カスケード: 介入1件が生む連鎖

`events.jsonl` の各イベントは原因イベントのID列（`parents`）を持つ。
神の介入・技術創発を根として子孫を辿り、**どの介入がどれほどの連鎖を生んだか**を数える。"""))
cells.append(code("""def load_events(run):
    evs = [json.loads(l) for l in (LOGS / run / "events.jsonl").read_text().splitlines() if l.strip()]
    return {e["id"]: e for e in evs}


def descendant_ids(events, root_id):
    children = {}
    for e in events.values():
        for p in e["parents"]:
            children.setdefault(p, []).append(e["id"])
    seen, stack = set(), [root_id]
    while stack:
        for c in children.get(stack.pop(), ()):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def cascade_table(run):
    events = load_events(run)
    roots = [e for e in events.values() if e["type"] in ("god_intervention", "tech_emergence")]
    rows = []
    for e in roots:
        desc = descendant_ids(events, e["id"])
        kinds = {}
        for d in desc:
            kinds[events[d]["type"]] = kinds.get(events[d]["type"], 0) + 1
        top = ", ".join(f"{k}x{v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])[:4])
        rows.append({"tick": e["tick"], "root_type": e["type"], "root": e["text"][:40],
                     "descendants": len(desc), "top_effects": top})
    return pd.DataFrame(rows).sort_values("descendants", ascending=False)


cascade_table("earth_earth_financial_crisis").head(8)"""))

cells.append(md("""### デフォルト連鎖（債務不履行の感染チェーン）

親イベントの型を見ると、**封鎖→輸入インフレ→金利上昇**で起きたデフォルトと、
**他国デフォルトのcredibility_hitから感染**したデフォルトが区別できる。"""))
cells.append(code("""events = load_events("earth_earth_financial_crisis")
rows = []
for e in sorted((e for e in events.values() if e["type"] == "sovereign_default"),
                key=lambda x: x["tick"]):
    rows.append({
        "tick": e["tick"], "nation": e["actor"],
        "rate%": round(e["data"]["rate"] * 100, 1),
        "debt_gdp": e["data"]["debt_gdp"],
        "parents": [events[p]["type"] for p in e["parents"]],
    })
pd.DataFrame(rows)"""))

cells.append(md("""## 3. 介入点×指標の感度行列

各シナリオの最終指標とbaselineの差分（`analysis/out/sensitivity_matrix.csv`）。
**同じseed・同じ世界**での差なので、差分は介入そのものに帰着できる。"""))
cells.append(code("""sens = pd.read_csv(OUT / "sensitivity_matrix.csv", index_col=0)
sens.round(2)"""))
cells.append(code("""ax = sens["world_gdp"].plot.barh(figsize=(7, 3), color="#f0883e")
ax.set_xlabel("世界GDPの最終差分（baseline比、指数値）")
ax.set_title("介入点がGDPに与える打撃: 金融感染 > 三重封鎖 > 単独封鎖")
for i, v in enumerate(sens["world_gdp"]):
    ax.text(v - 1, i, f"{v:+.1f}", va="center", ha="right")
plt.show()"""))

cells.append(md("""## 4. A/B反実仮想: 世界GDP系列

同一seed=42・同一地球プリセットで、介入だけを変えた場合の分岐。"""))
cells.append(code("""fig, ax = plt.subplots(figsize=(8, 4))
series = {
    "baseline": ("earth_baseline", "#8b949e"),
    "hormuz封鎖": ("earth_earth_hormuz", "#f0883e"),
    "三重危機(ホルムズ+台湾+スエズ)": ("earth_earth_triple_crisis", "#e5534b"),
    "金融危機(封鎖+利上げ8%)": ("earth_earth_financial_crisis", "#d6a8ff"),
}
for label, (run, color) in series.items():
    s = pd.read_csv(LOGS / run / "series.csv")
    ax.plot(s["tick"], s["world_gdp"], label=label, color=color, lw=2)
ax.set_xlabel("tick（月）"), ax.set_ylabel("世界GDP")
ax.legend(loc="lower left")
ax.set_title("神の介入による歴史の分岐（seed=42、A/B反実仮想）")
plt.show()"""))

cells.append(md("""## 5. IF史: 過去の介入を1つ差し替えて歴史を分岐させる

`whatif` ランナーは記録済みの歴史を分岐tickまで決定論的に再生し、介入を
差し込んで再実行する（分岐前は元の歴史とbit等価）。各分岐runの
`whatif.json` から「どこで歴史が変わったか」を読む。"""))
cells.append(code("""def _iv_label(iv):
    ps = ",".join(str(k) + "=" + str(v) for k, v in iv["params"].items())
    return iv["type"] + "(" + ps + ")"

rows = []
for wj in sorted(LOGS.glob("*/whatif.json")):
    r = json.loads(wj.read_text())
    d = r["final_metric_deltas"]
    rows.append({
        "fork": r["fork_run"], "base": r["base_run"],
        "IF": "t" + str(r["fork_tick"]) + " " + ", ".join(_iv_label(iv) for iv in r["interventions"]),
        "first_div": r["first_divergence_tick"],
        "d_gdp": d.get("world_gdp"), "d_defaults": d.get("defaults"),
        "only_in_base": "; ".join("t" + str(e["tick"]) + e["actor"] for e in r["only_in_base"])[:60],
        "only_in_fork": "; ".join("t" + str(e["tick"]) + e["actor"] for e in r["only_in_fork"])[:60],
    })
pd.DataFrame(rows)"""))

cells.append(md("""## 6. RL戦術層の学習曲線

単一国家学習（heuristic相手）と自己対戦学習（他の学習者も環境の一部）の
評価報酬推移。`models/*.curve.json` から読み込み。"""))
cells.append(code("""fig, ax = plt.subplots(figsize=(8, 4))
for f in sorted(MODELS.glob("*.curve.json")):
    c = json.loads(f.read_text())
    xs = [p["episode"] for p in c]
    if "eval_reward" in c[0]:
        ys = [p["eval_reward"] for p in c]
    else:  # self-play: per-nation eval -> mean
        ys = [sum(p["eval"].values()) / len(p["eval"]) for p in c]
    ax.plot(xs, ys, label=f.stem, marker=".")
ax.set_xlabel("episode"), ax.set_ylabel("評価報酬")
ax.legend()
ax.set_title("RL戦術層: 脆弱国ほど学習利得が大きい / 自己対戦は共進化")
plt.show()"""))

cells.append(md("""## 7. LLM戦略層の思考ログ

`--policy llm`（z.ai GLM）実行の `policy_shift` イベントには、国家AIが
残した判断の理由（rationale）がそのまま記録されている。"""))
cells.append(code("""llm_runs = [p for p in sorted(LOGS.iterdir())
            if (p / "run.json").exists() and "llm" in p.name]
if not llm_runs:
    print("LLM実行ログ未コミット（earth_llm_hormuz 完了後に再実行）")
for d in llm_runs:
    evs = [json.loads(l) for l in (d / "events.jsonl").read_text().splitlines() if l.strip()]
    rationales = [e for e in evs
                  if e["type"] == "policy_shift" and len(e["text"]) > 55
                  and "doctrine:" not in e["text"]]
    print(f"\\n### {d.name} — LLM rationale {len(rationales)} 件")
    for e in sorted(rationales, key=lambda x: -len(x["text"]))[:6]:
        body = e["text"].split(":", 1)[-1].strip()
        print(f"  t{e['tick']:>2} {e['actor']}: {body[:150]}")"""))

cells.append(md("""## まとめ: 介入点と連鎖の対応

| 介入点 | 観測された連鎖 | 副作用 |
|---|---|---|
| 海峡封鎖（ホルムズ） | エネルギー価格+50% → ファブ電力不足 → 半導体+31% → GDP -26.5% | 債務国の金利上昇 |
| 利上げ（世界金利+8%） | 債務国の利払い急増 → デフォルト → 債権国へcredibility_hit感染 | GDPへの打撃は三重封鎖超 |
| ベイルアウト | デフォルト計4件→3件 | GDP回復は限定的（モラルハザードの均衡） |
| 技術禁止（核融合ban） | 未来技術による海峡ショック吸収が消失 → エネルギー1.35 | 技術格差の固定化 |

詳細な図表は `analysis/out/`（生成スクリプト `analysis/make_figures.py`）。"""))

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata.kernelspec = {"display_name": "Python 3", "language": "python", "name": "python3"}

path = ROOT / "analysis" / "terrarium_analysis.ipynb"
nbf.write(nb, str(path))
print(f"wrote {path} ({len(cells)} cells)")

# execute in place so outputs are embedded
from nbclient import NotebookClient

nb_client = NotebookClient(nb, timeout=300, kernel_name="python3",
                           resources={"metadata": {"path": str(ROOT / "analysis")}})
nb_client.execute()
nbf.write(nb, str(path))
print(f"executed and saved {path}")
sys.exit(0)
