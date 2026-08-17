"""earth_all: すべての国をAI国家化するプリセット（手続き生成）。

Natural Earth 110m の全特徴（南極等を除く約170カ国）をそれぞれ1つのAI国家とし、
主要国は概算データ（GDP/軍事/債務/資源）のテーブルで、その他の国は安定した
デフォルトで初期化する。世界全体の需給は worldgen のトップアップ処理で
1.15倍以上を保証し、航路も実際の海峡を経由させて自動生成する。
数値は公開情報の簡易概算（中立的・分析目的）。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .models import Chokepoint, Commodity, NationSpec, ResourceKind, TradeRoute, WorldSpec
from .worldgen import REAL_CHOKEPOINTS, CONSUMPTION, RESOURCE_COMMO, YIELD_PER_UNIT, _supply

REPO = Path(__file__).resolve().parents[4]
GEOJSON = REPO / "web" / "world.geojson"

# 主要国テーブル: ADMIN名 -> (gdp_t, military, stability, debt_gdp, aggression, paranoia, resources)
# 数値は2024年前後の公開概算。resources は経済構造の大まかな表現。
DATA: dict[str, tuple] = {
    "United States of America": (27.4, 100, 60, 122, 0.40, 0.40, ["oil", "gas", "grain", "grain", "grain", "fab", "finance", "finance", "orbit", "orbit", "mineral"]),
    "China": (17.8, 85, 58, 111, 0.55, 0.60, ["fab", "fab", "mineral", "mineral", "mineral", "grain", "oil", "orbit", "finance"]),
    "Japan": (4.2, 25, 66, 252, 0.15, 0.55, ["fab", "fab", "finance", "orbit"]),
    "Germany": (4.5, 20, 68, 82, 0.15, 0.35, ["fab", "grain", "finance", "coal"]),
    "India": (3.6, 55, 55, 82, 0.40, 0.55, ["grain", "grain", "fab", "mineral", "orbit"]),
    "United Kingdom": (3.3, 35, 64, 101, 0.25, 0.40, ["finance", "finance", "gas", "fab", "orbit"]),
    "France": (3.0, 30, 60, 110, 0.25, 0.35, ["grain", "fab", "finance", "orbit", "nuclear"]),
    "Italy": (2.2, 20, 58, 135, 0.15, 0.35, ["fab", "finance", "grain"]),
    "Brazil": (2.1, 20, 55, 84, 0.20, 0.30, ["grain", "grain", "grain", "oil", "mineral"]),
    "Canada": (2.1, 15, 72, 107, 0.15, 0.30, ["oil", "gas", "grain", "grain", "mineral"]),
    "Russia": (2.0, 70, 50, 92, 0.65, 0.70, ["oil", "gas", "gas", "grain", "mineral", "orbit"]),
    "Mexico": (1.8, 15, 52, 93, 0.25, 0.40, ["oil", "grain", "fab"]),
    "Australia": (1.7, 15, 74, 57, 0.15, 0.30, ["gas", "grain", "grain", "mineral", "mineral"]),
    "South Korea": (1.7, 45, 62, 98, 0.25, 0.60, ["fab", "fab", "fab", "finance", "orbit"]),
    "Spain": (1.6, 12, 62, 105, 0.10, 0.30, ["grain", "fab", "finance"]),
    "Indonesia": (1.4, 25, 55, 62, 0.30, 0.45, ["grain", "mineral", "oil", "fab"]),
    "Netherlands": (1.1, 10, 72, 96, 0.10, 0.30, ["fab", "finance", "grain"]),
    "Saudi Arabia": (1.0, 40, 55, 80, 0.35, 0.50, ["oil", "oil", "oil", "finance"]),
    "Turkey": (1.1, 40, 52, 75, 0.50, 0.55, ["fab", "grain", "gas"]),
    "Switzerland": (0.9, 8, 80, 75, 0.05, 0.25, ["finance", "finance"]),
    "Taiwan": (0.78, 25, 60, 90, 0.20, 0.65, ["fab", "fab", "fab", "fab"]),
    "Poland": (0.85, 25, 60, 92, 0.35, 0.50, ["grain", "fab", "coal"]),
    "Argentina": (0.65, 15, 50, 155, 0.25, 0.35, ["grain", "grain", "grain", "gas"]),
    "Sweden": (0.6, 10, 74, 65, 0.10, 0.30, ["fab", "mineral", "finance"]),
    "Belgium": (0.65, 8, 70, 106, 0.10, 0.30, ["fab", "finance"]),
    "Thailand": (0.55, 20, 52, 104, 0.25, 0.40, ["grain", "fab", "tourism"]),
    "Israel": (0.55, 40, 55, 120, 0.45, 0.70, ["fab", "fab", "tech"]),
    "United Arab Emirates": (0.52, 15, 68, 78, 0.25, 0.40, ["oil", "finance", "logistics"]),
    "Norway": (0.5, 12, 80, 74, 0.10, 0.30, ["oil", "gas", "finance", "fish"]),
    "Denmark": (0.42, 8, 78, 72, 0.10, 0.30, ["grain", "wind", "finance"]),
    "Singapore": (0.55, 12, 75, 85, 0.10, 0.35, ["fab", "finance", "logistics"]),
    "Austria": (0.53, 8, 72, 105, 0.05, 0.30, ["fab", "finance"]),
    "Nigeria": (0.4, 15, 42, 96, 0.35, 0.50, ["oil", "gas", "grain"]),
    "Egypt": (0.45, 45, 48, 130, 0.40, 0.60, ["gas", "grain", "logistics"]),
    "South Africa": (0.4, 20, 50, 98, 0.25, 0.40, ["mineral", "mineral", "grain"]),
    "Iran": (0.45, 60, 45, 90, 0.60, 0.70, ["oil", "gas", "mineral"]),
    "Malaysia": (0.45, 12, 58, 108, 0.20, 0.35, ["grain", "mineral", "fab"]),
    "Philippines": (0.45, 12, 55, 101, 0.25, 0.45, ["grain", "mineral", "fab"]),
    "Vietnam": (0.5, 25, 55, 102, 0.35, 0.50, ["fab", "grain", "mineral"]),
    "Pakistan": (0.4, 55, 42, 100, 0.50, 0.65, ["grain", "mineral"]),
    "Bangladesh": (0.45, 12, 50, 85, 0.20, 0.40, ["grain", "fab"]),
    "Chile": (0.35, 10, 60, 98, 0.15, 0.30, ["mineral", "mineral", "grain", "finance"]),
    "Colombia": (0.4, 15, 50, 95, 0.30, 0.45, ["oil", "grain", "mineral"]),
    "Finland": (0.32, 12, 76, 78, 0.10, 0.35, ["fab", "mineral"]),
    "Czechia": (0.35, 10, 68, 105, 0.10, 0.30, ["fab", "grain"]),
    "Portugal": (0.3, 8, 68, 120, 0.05, 0.30, ["fab", "grain"]),
    "Romania": (0.35, 15, 56, 110, 0.25, 0.45, ["grain", "fab", "gas"]),
    "New Zealand": (0.26, 5, 78, 66, 0.05, 0.25, ["grain", "grain", "fish"]),
    "Peru": (0.28, 10, 48, 87, 0.20, 0.35, ["mineral", "mineral", "grain"]),
    "Greece": (0.28, 15, 55, 153, 0.15, 0.40, ["logistics", "grain", "finance"]),
    "Iraq": (0.28, 20, 40, 90, 0.45, 0.60, ["oil", "oil", "gas"]),
    "Algeria": (0.26, 25, 45, 88, 0.40, 0.55, ["oil", "gas", "mineral"]),
    "Kazakhstan": (0.28, 12, 52, 95, 0.20, 0.40, ["oil", "grain", "grain", "mineral"]),
    "Qatar": (0.24, 10, 70, 80, 0.20, 0.40, ["gas", "gas", "finance"]),
    "Kuwait": (0.16, 8, 65, 85, 0.15, 0.40, ["oil", "finance"]),
    "Venezuela": (0.1, 15, 32, 150, 0.45, 0.60, ["oil", "oil", "mineral"]),
    "Ukraine": (0.19, 45, 45, 188, 0.40, 0.60, ["grain", "grain", "grain", "mineral"]),
    "Hungary": (0.22, 8, 60, 109, 0.15, 0.40, ["fab", "grain"]),
    "Morocco": (0.16, 10, 52, 93, 0.25, 0.40, ["grain", "mineral", "logistics"]),
    "Ethiopia": (0.15, 10, 42, 88, 0.35, 0.55, ["grain"]),
    "Kenya": (0.12, 8, 50, 95, 0.20, 0.40, ["grain", "logistics"]),
    "Libya": (0.08, 8, 30, 90, 0.40, 0.60, ["oil", "oil"]),
    "Dem. Rep. Congo": (0.07, 10, 30, 90, 0.35, 0.55, ["mineral", "mineral", "mineral"]),
    "Azerbaijan": (0.08, 10, 50, 92, 0.35, 0.55, ["gas", "oil"]),
    "Oman": (0.12, 8, 62, 80, 0.20, 0.40, ["oil", "gas"]),
    "Uzbekistan": (0.1, 8, 52, 90, 0.25, 0.45, ["grain", "mineral"]),
    "Myanmar": (0.07, 12, 35, 130, 0.40, 0.60, ["grain", "mineral"]),
    "Sudan": (0.05, 10, 30, 260, 0.45, 0.60, ["grain", "oil"]),
}

# GeoJSON名の別名（テーブルkeyとの差異を吸収）
ALIAS = {"Republic of Serbia": "Serbia", "United Republic of Tanzania": "Tanzania",
         "Republic of the Congo": "Congo", "Dominican Rep.": "Dominican Republic",
         "Bosnia and Herz.": "Bosnia", "Macedonia": "North Macedonia",
         "Côte d'Ivoire": "Cote d'Ivoire", "Lao PDR": "Laos"}

PERSONA = {
    "super": "巨大経済・軍事大国。供給網と金融で覇権を維持し、他国の動向に敏感。",
    "industrial": "工業と輸出主導の経済大国。エネルギーと原料を輸入に頼る。",
    "tech": "半導体・ハイテクの中核。技術と外交カードを盾にする。",
    "resource": "資源輸出国。価格と航路が国運を左右する。",
    "emerging": "急成長する新興経済。食料とエネルギーの確保が最優先。",
    "finance": "金融・物流のハブ。安定と信頼が商品。",
    "small": "小規模経済。大国の席巻を避け、生存と実利の外交を旨とする。",
}

# テーブル内の補助的表現を既存リソース種へ写像
EXTRA_MAP = {"logistics": "finance", "tech": "fab", "fish": "grain",
             "wind": "gas", "coal": "mineral", "nuclear": "gas", "tourism": "finance"}


def _persona_for(res: list[str], gdp: float) -> str:
    kinds = set(res)
    if gdp >= 10: return PERSONA["super"]
    if "fab" in kinds and gdp >= 1.0: return PERSONA["tech"]
    if kinds & {"oil", "gas"} and gdp < 3: return PERSONA["resource"]
    if "finance" in kinds and gdp < 1.5: return PERSONA["finance"]
    if gdp >= 0.5: return PERSONA["industrial"]
    if gdp >= 0.15: return PERSONA["emerging"]
    return PERSONA["small"]


def _centroid(feature: dict) -> tuple[float, float] | None:
    """最大リングのbbox中心（簡易重心）。"""
    g = feature.get("geometry")
    if not g: return None
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    best, best_area = None, -1.0
    for poly in polys:
        ring = poly[0]
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if area > best_area:
            best_area = area
            best = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
    return best


def _lon_dist(a: float, b: float) -> float:
    return min(abs(a - b), 360 - abs(a - b))


def _topup(rng: random.Random, specs: list[NationSpec]) -> None:
    """世界の需給バランス: 供給 ≥ 需要×1.15 まで主要国に資源ユニットを追加。"""
    for _ in range(400):
        supply = {c: 0.0 for c in CONSUMPTION}
        for sp in specs:
            for c, v in _supply(sp.resources).items():
                supply[c] += v
        demand = {k: v * len(specs) for k, v in CONSUMPTION.items()}
        deficits = {c: demand[c] * 1.15 - supply[c] for c in supply}
        worst = max(deficits, key=lambda c: deficits[c])
        if deficits[worst] <= 0:
            return
        # 大きい経済主体から（実世界の生産能力を概算反映）
        hosts = sorted(specs, key=lambda s: -s.gdp_t)
        hosts = [h for h in hosts if len(h.resources) < 10]
        if not hosts: return
        add = {"energy": "oil", "food": "grain", "chips": "fab",
               "minerals": "mineral", "space": "orbit"}[worst]
        hosts[0].resources.append(ResourceKind(add))


def _routes(rng: random.Random, specs: list[NationSpec], cps: list[Chokepoint]) -> list[TradeRoute]:
    """需給に基づき輸入国→上位輸出国2社の航路を生成。海峡は回廊近傍から選ぶ。"""
    routes: list[TradeRoute] = []
    supply = {sp.id: _supply(sp.resources) for sp in specs}
    for c in CONSUMPTION:
        cons = CONSUMPTION[c]
        spare = {sp.id: max(0.0, supply[sp.id][c] - cons) for sp in specs}
        for sp in specs:
            deficit = cons - supply[sp.id][c]
            if deficit <= 0.05: continue
            exporters = sorted([o for o in specs if o.id != sp.id and spare.get(o.id, 0) > 0.05],
                               key=lambda o: -spare[o.id])
            remaining = deficit
            for exp in exporters[:2]:
                cover = min(remaining, spare[exp.id])
                if cover <= 0.05: continue
                share = round(min(1.0, cover / cons), 2)
                remaining -= cover; spare[exp.id] -= cover
                cp_names = []
                if c != "space" and rng.random() < 0.7:
                    mid_lon = (sp.centroid[0] + exp.centroid[0]) / 2
                    mid_lat = (sp.centroid[1] + exp.centroid[1]) / 2
                    nearest = min(cps, key=lambda cp: _lon_dist(cp.lon, mid_lon) ** 2 + (cp.lat - mid_lat) ** 2)
                    cp_names = [nearest.name]
                routes.append(TradeRoute(importer=sp.id, exporter=exp.id, commodity=Commodity(c),
                                         share=share, chokepoints=cp_names))
                if remaining <= 0.05: break
    return routes


def build_earth_all(seed: int = 7) -> WorldSpec:
    rng = random.Random(f"earth_all:{seed}")
    geo = json.loads(GEOJSON.read_text(encoding="utf-8"))

    specs: list[NationSpec] = []
    used_ids: set[str] = set()
    for feat in geo["features"]:
        admin = feat["properties"].get("ADMIN") or feat["properties"].get("NAME") or ""
        if not admin: continue
        ctr = _centroid(feat)
        if ctr is None: continue
        if ctr[1] < -59: continue                      # 南極・亜南極は除外
        key = ALIAS.get(admin, admin)
        d = DATA.get(key)
        if d:
            gdp, mil, stab, debt, aggr, para, res = d
            res = [ResourceKind(EXTRA_MAP.get(r, r)) for r in res]
            pop = max(1.0, gdp * 40)
        else:
            gdp = round(rng.uniform(0.02, 0.12), 3)
            mil, stab, debt = round(rng.uniform(1, 6), 1), round(rng.uniform(42, 66), 1), round(rng.uniform(30, 95), 1)
            aggr, para = round(rng.uniform(0.1, 0.4), 2), round(rng.uniform(0.2, 0.5), 2)
            res = []
            pop = round(rng.uniform(0.5, 15), 1)
        nid = "".join(ch for ch in key.upper() if ch.isascii() and ch.isalpha())[:3] or "X"
        if nid in used_ids:
            # 同じ3文字を主張する国が複数ある場合は2文字+連番で決定論的に解決
            pfx, k = nid[:2], 0
            while k < 26 and pfx + chr(ord("A") + k) in used_ids:
                k += 1
            nid = pfx + chr(ord("A") + k) if k < 26 else f"{nid}{used_ids.__len__()}"
            while nid in used_ids:
                nid += "X"
        used_ids.add(nid)
        # 社会・エネルギーパラメータは経済規模と資源構造から決定論的に導出
        fossil = any(r in (ResourceKind.OIL, ResourceKind.GAS) for r in res)
        education = round(min(0.92, 0.38 + 0.30 * min(1.0, gdp / 2.0) + 0.08 * (len(res) >= 4)), 2)
        gini = round(min(0.60, 0.33 + 0.18 * max(0.0, 1.0 - gdp / 2.0) + (0.05 if fossil else 0.0)), 2)
        renew = round(max(0.02, min(0.60, 0.08 + (0.22 if not fossil else 0.0) + min(0.18, gdp * 0.012))), 2)
        popg = round(min(0.025, max(-0.004, 0.018 - gdp * 0.002)), 3)
        specs.append(NationSpec(
            id=nid, name=admin, persona=_persona_for(res, gdp),
            color=f"hsl({(len(specs) * 137.508) % 360:.0f}, 52%, 50%)",
            centroid=ctr, geo_ids=[admin], population_m=pop,
            gdp_t=gdp, military=mil, stability=stab, approval=50.0,
            aggression=aggr, paranoia=para, resources=res, debt_gdp=debt,
            population_growth=popg, education=education, gini=gini, energy_renew=renew,
        ))

    specs.sort(key=lambda s: s.id)
    _topup(rng, specs)
    # 核保有の初期保有国（公開情報の概算。NE名→生成id）
    by_name = {sp.name: sp.id for sp in specs}
    nuclear_names = ["United States of America", "Russia", "China", "United Kingdom",
                     "France", "India", "Pakistan", "Israel", "North Korea"]
    holders = [by_name[n] for n in nuclear_names if n in by_name]
    cps = [Chokepoint(name=n, lon=lo, lat=la) for n, lo, la in REAL_CHOKEPOINTS]
    routes = _routes(rng, specs, cps)
    return WorldSpec(name="earth_all", map_geojson="world.geojson",
                     nations=specs, chokepoints=cps, routes=routes,
                     factor_holders={"nuclear": holders})
