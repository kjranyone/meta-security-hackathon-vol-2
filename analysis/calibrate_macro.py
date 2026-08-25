"""マクロ時定数の較正: 2008年失業率経路(オークン則)と1973-74年CPI(パススルー)。

ターゲット(公開統計の概算):
  2008年米国: U3失業率 5.0%(2008-01)→6.0(mo5)→7.2(mo10)→8.5(mo15)→10.0(mo21)
    — GDPギャップ約-6%が持続した場合の調整経路。半減期~9ヶ月に相当
  1973-74年米国: CPI 6.2%(1973)→11.0%(1974) — 輸入価格ショックの+
    4.8pt。禁輸近似(主要海峡24ヶ月封鎖)のシミュレーション平均インフレで近似

Usage: uv run --project server python analysis/calibrate_macro.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "src"))

OKUN_2008 = [(0, 5.0), (5, 6.0), (10, 7.2), (15, 8.5), (21, 10.0)]


def fit_okun() -> dict:
    """失業率の一次遅れ du/dt = a(u* - u) を2008年経路にフィット。
    u* = 5.0 + 160×0.06×(21/12)相当の持続ギャップ ... 実務上は
    u*=11.5(定常)を仮定し半減期をデータに合わせる。"""
    best = None
    for tau_h in (2700.0, 5000.0, 7000.0, 9100.0, 12000.0, 16000.0):
        a = 1.0 - math.exp(-730.0 / tau_h)          # 月次の調整率
        u_star, u0 = 11.5, 5.0
        path = []
        u = u0
        for m in range(22):
            path.append(u)
            u = u + a * (u_star - u)
        err = sum((path[m] - target) ** 2 for m, target in OKUN_2008)
        if best is None or err < best["err"]:
            best = {"tau_h": tau_h, "err": round(err, 2),
                    "path_at_targets": [round(path[m], 2) for m, _ in OKUN_2008]}
    return best


def fit_pass_through() -> dict:
    """禁輸近似で平均インフレの上昇幅を1973-74(+4.8pt)に合わせる。"""
    import terrarium.sim.engine as E
    from terrarium.agents.heuristic import HeuristicPolicy
    from terrarium.sim.engine import Engine
    from terrarium.sim.interventions import Intervention
    from terrarium.world.presets import load_preset

    results = []
    for cap in (0.15, 0.25, 0.35, 0.50):
        E.IMPORT_INFLATION_CAP = cap
        spec = load_preset("earth_all")
        eng = Engine(spec, {ns.id: HeuristicPolicy() for ns in spec.nations},
                     seed=42, out_dir=None)
        eng.open_replay()
        for t in range(14):
            eng.tick_no = t
            if t == 0:
                for cp in ("Strait of Hormuz", "Strait of Malacca", "Suez Canal"):
                    eng.apply_intervention(Intervention(
                        tick=0, type="close_chokepoint",
                        params={"chokepoint": cp, "duration": 24}))
            eng.step()
        eng.close()
        i0, i1 = eng.series[0]["mean_inflation"], max(s["mean_inflation"] for s in eng.series)
        results.append({"cap": cap, "infl_rise_pt": round((i1 - i0) * 100, 2)})
        print(f"cap={cap:.2f} mean_inflation rise = +{(i1-i0)*100:.2f}pt (target +4.8)", flush=True)
    best = min(results, key=lambda r: abs(r["infl_rise_pt"] - 4.8))
    return {"target_pt": 4.8, "best": best, "all": results}


def main() -> int:
    okun = fit_okun()
    print("OKUN best:", okun)
    pt = fit_pass_through()
    print("PASS-THROUGH best:", pt)
    out = Path(__file__).resolve().parents[1] / "analysis" / "out" / "calibration_macro.json"
    out.write_text(json.dumps({"okun_2008": {"target": OKUN_2008, "fit": okun},
                               "pass_through_1973": pt}, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
