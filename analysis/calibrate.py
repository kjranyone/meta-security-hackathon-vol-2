"""時定数の較正: 実歴史データへの形状フィット。

対象エピソード（公開されている月次油価の概算から）:
  1990年 湾岸危機: クウェート侵攻(7月)→油価 $17→$40(×2.3)、ピークまで~2.5ヶ月、
  戦争終結(2月)後~3ヶ月で半減。海峡経由輸出の実質停止として近似する。

較正対象パラメータ（clock.py）:
  PRICE_TAU   価格発見の時定数 — ピーク到達時間を支配
  REROUTE_TAU 封鎖実効化の時定数 — 上昇の立ち上がり形状を支配

目的関数: (ピーク倍率, ピーク時刻, 回復半減期) の実データとの二乗誤差。
グリッドサーチは決定論シミュレーション(earth, seed固定)の上で行う。

Usage: uv run --project server python analysis/calibrate.py
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "src"))

from terrarium.agents.heuristic import HeuristicPolicy  # noqa: E402
from terrarium.sim.engine import Engine  # noqa: E402
from terrarium.sim.interventions import Intervention, Scenario  # noqa: E402
from terrarium.world import clock as TC  # noqa: E402
from terrarium.world.presets import load_preset  # noqa: E402

# 1990年湾岸危機の較正ターゲット（月次油価の公開概算から）
TARGET = {"peak_mult": 2.3, "t_peak_mo": 2.5, "half_recovery_mo": 3.0}


def run_case(price_tau: float, reroute_tau: float, reopen_tau: float = 96.0,
             seed: int = 11) -> dict:
    """ホルムズ6ヶ月封鎖→再開(湾岸危機の近似)の価格経路を返す。"""
    TC.PRICE_TAU = price_tau
    TC.REROUTE_TAU = reroute_tau
    TC.REOPEN_TAU = reopen_tau
    spec = load_preset("earth")
    eng = Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                 seed=seed, out_dir=None)
    ivs = [Intervention(tick=0, type="close_chokepoint",
                        params={"chokepoint": "Strait of Hormuz", "duration": 6})]
    eng.open_replay()
    path = []
    for t in range(15):
        eng.tick_no = t
        for iv in ivs:
            if iv.tick == t:
                eng.apply_intervention(iv)
        eng.step()
        path.append(eng.prices["energy"])
    eng.close()
    peak = max(path)
    t_peak = path.index(peak)
    reopen = path[6]
    # 再開後3ヶ月での回復度
    post = path[min(9, len(path) - 1)]
    return {"peak_mult": peak, "t_peak_mo": t_peak, "post3": post,
            "path": [round(p, 3) for p in path]}


def score(res: dict) -> float:
    # 回復: 再開3ヶ月後にピーク上昇分の半分以上戻っていること(1 + (peak-1)/2)
    target_post3 = 1.0 + (TARGET["peak_mult"] - 1.0) / 2
    return ((res["peak_mult"] - TARGET["peak_mult"]) ** 2
            + (res["t_peak_mo"] - TARGET["t_peak_mo"]) ** 2 * 0.3
            + (res["post3"] - target_post3) ** 2)


def main() -> int:
    grid_p = [12.0, 24.0, 36.0]
    grid_r = [120.0, 240.0]
    grid_o = [96.0, 240.0, 720.0, 1440.0, 2160.0]
    results = []
    for pt, rt, ot in itertools.product(grid_p, grid_r, grid_o):
        res = run_case(pt, rt, ot)
        s = score(res)
        results.append({"price_tau": pt, "reroute_tau": rt, "reopen_tau": ot,
                        "score": round(s, 4), **res})
    for r in sorted(results, key=lambda r: r["score"])[:8]:
        print(f"PT={r['price_tau']:4.0f} RT={r['reroute_tau']:4.0f} OT={r['reopen_tau']:5.0f} "
              f"peak={r['peak_mult']:.2f} t_peak={r['t_peak_mo']}mo "
              f"post3={r['post3']:.2f} score={r['score']:.3f}", flush=True)
    best = min(results, key=lambda r: r["score"])
    print("\nBEST:", json.dumps({k: v for k, v in best.items() if k != "path"}))
    out = Path(__file__).resolve().parent / "out" / "calibration.json"
    out.write_text(json.dumps({"target": TARGET, "best": best,
                               "all": [{k: v for k, v in r.items() if k != "path"}
                                       for r in sorted(results, key=lambda r: r["score"])]},
                              ensure_ascii=False, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
