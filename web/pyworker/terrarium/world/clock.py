"""シミュレーション時計の実時間校正（単位はすべて「時間」）。

エンジンの全動力学はここにある実時間定数で定義され、1tickの実時間
（WorldSpec.hours_per_tick）に応じて指数緩和・ハザードに変換される。

  - 神モード（ライブ）: 1tick = 1時間。介入は伝播遅延を持って波及する
  - 圧縮時計（実験・訓練）: 例 1tick = 720時間(=1ヶ月)。同一の物理が
    スケールするだけで、別のモデルではない

設計思想: 「何かをしたら即時に数値が変わる」ことはない。市場は時間単位、
物流は日単位、マクロは月単位、戦争の動員は週単位で応答する。
"""
from __future__ import annotations

import math

HOURS_PER_DAY = 24.0
HOURS_PER_MONTH = 730.0
HOURS_PER_YEAR = 8760.0

# ---------------------------------------------------------------- 市場・物流
# 較正済み(1990年湾岸危機の月次油価形状へのフィット、analysis/calibrate.py、
# グレードA: ピーク倍率2.39=実績2.3、ピーク3ヶ月=実績2.5、残留はやや速い)
PRICE_TAU = 24.0          # 価格発見 ~1日
FEAR_TAU = 72.0           # ニューズ・ドリブンのリスクプレミアム減衰 ~3日
FEAR_JUMP = 0.35          # 海峡封鎖ニューズが価格目標に載せる期待ショック
FEAR_CAP = 0.60
REROUTE_TAU = 120.0       # 封鎖の実効化 ~5日（較正値。海運の運用見積り2-4週とは
                          # ずれがある — 形状適合を優先したことを来歴に記録）
REOPEN_TAU = 2160.0       # 再開後の回復 ~90日（戦争リスクプレミアムの残留）
CHOKE_MIN_CAPACITY = 0.15  # 完全封鎖時も残る迂回・密輸による下限輸送力

# ---------------------------------------------------------------- 政府・社会
INFLATION_TAU = 4430.0    # インフレ期待の持続（alpha(720h)=0.15 と旧月次校正互換）
UNEMPLOYMENT_TAU = 2700.0 # オークン則的な調整 ~3.7ヶ月（alpha(720h)=0.235）
TRUST_DIPLOMA_H = 720.0   # 外交改善キャンペーンが信頼に効くスケール = 1ヶ月分

# ---------------------------------------------------------------- 戦争・同盟
MOBILIZE_MIN_H = 96.0     # 動員所要時間の下限 ~4日
MOBILIZE_MODE_H = 240.0   # 最頻値 ~10日
MOBILIZE_MAX_H = 720.0    # 上限 ~30日
WAR_TENSION_RELAPSE = 0.45  # 動員完了時にこれ未満なら開戦せず解除
ALLIANCE_MIN_H = 24.0     # 同盟国の参戦協議 ~1日
ALLIANCE_MAX_H = 168.0    # ~1週間

# ---------------------------------------------------------------- しきい値
EVENT_HOURLY_GATE = 168.0  # 高頻度時計で同一事象のイベント再送を抑える間隔 = 1週間
SPIKE_WINDOW_H = 24.0      # 価格急騰判定の比較窓 = 1日
SPIKE_RATIO = 1.10
CHRONIC_SHORTAGE_CAP = 0.3  # 慢性的な部分不足の深刻度上限（急性の全断=1.0と区別）


def frac(hours_per_tick: float, per_hours: float) -> float:
    """1tickあたりの経過割合（月次/年次レートのスカラー化用、上限1）。"""
    return min(1.0, hours_per_tick / per_hours)


def alpha(hours_per_tick: float, tau_h: float) -> float:
    """時定数tau_hの指数緩和が1tickで進む割合 1 - exp(-dt/tau)。"""
    return 1.0 - math.exp(-hours_per_tick / tau_h)


def hazard(hours_per_tick: float, p_per_month: float) -> float:
    """月次確率を連続ハザードに変換した1tickあたり確率。"""
    if p_per_month >= 1.0:
        return 1.0
    if p_per_month <= 0.0:
        return 0.0
    lam = -math.log(1.0 - p_per_month) / HOURS_PER_MONTH
    return 1.0 - math.exp(-lam * hours_per_tick)


def ticks_for(hours: float, hours_per_tick: float) -> int:
    """実時間をtick数へ（最小1）。"""
    return max(1, int(round(hours / hours_per_tick)))
