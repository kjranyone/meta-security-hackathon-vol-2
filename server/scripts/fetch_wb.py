"""世界銀行APIから実データを取得し world/wb_data.json を生成する。

指標（すべて「最新の非NULL値」を取得: mrnev=1）:
  NY.GDP.MKTP.CD     GDP（US$）
  SP.POP.TOTL        総人口
  SL.UEM.TOTL.ZS     失業率（%労働力）
  GC.DOD.TOTL.GD.ZS  中央政府債務（%GDP、途上国は欠損多し）
  MS.MIL.XPND.GD.ZS  軍事費（%GDP、SIPRI）
  SI.POV.GINI        ジニ係数
  EG.FEC.RNEW.ZS     再生可能エネルギー消費比率（%）
  PV.EST             WGI 政治の安定・暴力の不在（推定値 -2.5..2.5）

APIキー不要。geojson（Natural Earth）の ISO_A3 で照合し、ADMIN名をキーに保存。
欠損は既存の手概算・決定論的導出にフォールバック（値は上書きしない）。

Usage: uv run python scripts/fetch_wb.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
GEO = SERVER.parent / "web" / "world.geojson"
OUT = SERVER / "src" / "terrarium" / "world" / "wb_data.json"

INDICATORS = {
    "gdp_usd": "NY.GDP.MKTP.CD",
    "population": "SP.POP.TOTL",
    "unemployment": "SL.UEM.TOTL.ZS",
    "debt_gdp": "GC.DOD.TOTL.GD.ZS",
    "mil_exp_pct": "MS.MIL.XPND.GD.ZS",
    "gini": "SI.POV.GINI",
    "renewables_pct": "EG.FEC.RNEW.ZS",
    "wgi_stability": "GOV_WGI_PV.EST",  # WGI政治安定(ESG source=75経由)
}


def fetch(indicator: str) -> dict[str, float]:
    """全カ国の最新非NULL値を1リクエストで取得。戻り値: ISO3 -> value。"""
    url = (f"https://api.worldbank.org/v2/country/ALL/indicator/{indicator}"
           f"?format=json&per_page=20000&mrnev=1&source=75")
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.loads(r.read().decode())
    rows = data[1] or []
    out = {}
    for row in rows:
        if row["value"] is None:
            continue
        iso = row["countryiso3code"]
        if len(iso) == 3 and iso != "WLD":
            out[iso] = float(row["value"])
    return out


def main() -> int:
    geo = json.loads(GEO.read_text())
    admins = {}
    for f in geo["features"]:
        p = f["properties"]
        iso = p.get("ISO_A3_EH") or p.get("ISO_A3") or ""
        if iso in ("-99", "", None):
            iso = p.get("WB_A3") or p.get("ADM0_A3") or ""
        admins[p["ADMIN"]] = iso if iso not in ("-99",) else ""
        # Natural Earth自身の推定値も保存（フォールバック用）
    ne = {p_f["properties"]["ADMIN"]: {
        "ne_pop": p_f["properties"].get("POP_EST"),
        "ne_gdp_md": p_f["properties"].get("GDP_MD"),
    } for p_f in geo["features"]}

    result: dict[str, dict] = {}
    for key, ind in INDICATORS.items():
        try:
            vals = fetch(ind)
        except Exception as e:
            print(f"[wb] {key} ({ind}) FAILED: {e}", file=sys.stderr)
            vals = {}
        n_hit = 0
        for admin, iso in admins.items():
            result.setdefault(admin, {})
            if iso and iso in vals:
                result[admin][key] = round(vals[iso], 4)
                n_hit += 1
        print(f"[wb] {key}: {n_hit}/{len(admins)} countries matched")

    # Natural Earth埋め込み推定でフォールバック
    for admin, d in ne.items():
        if "gdp_usd" not in result.get(admin, {}) and d["ne_gdp_md"] and d["ne_gdp_md"] > 0:
            result.setdefault(admin, {})["gdp_usd"] = round(d["ne_gdp_md"] * 1e6, 0)
        if "population" not in result.get(admin, {}) and d["ne_pop"] and d["ne_pop"] > 0:
            result[admin]["population"] = int(d["ne_pop"])

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
    cov = sum(1 for a in result if "gdp_usd" in result[a])
    print(f"[wb] wrote {OUT} ({len(result)} admins, GDP covered {cov})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
