"""非決定戦略因子（Strategic Factors）のデータモデル。

「核保有・放棄・新規保有」のような、国家AIの**戦略的自己選択**によって変化する
離散的ケイパビリティ/レジームを、エンジンにハードコードせずデータで定義する。

設計:
- FactorSpec: 因子の定義（取得期間・前提条件・初期保有国・効果パラメータ）
- 国家は doctrines[nuclear] = pursue | hold | abandon を毎tickの意思決定で選ぶ
  （heuristic/LLM/RL どのpolicyも同じプロトコルで戦略を表明できる）
- エンジンは取得進捗（factor_progress）を積算し、100%で保有へ遷移。
  遺棄は3tickの継続表明で確定。全てイベント（parentリンク付き）として記録。

新しい因子（輸出規制レジーム、通貨ブロック、核傘…）は CATALOG に
FactorSpec を足すだけで、エンジン・UI・ログは変更不要。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FactorSpec(BaseModel):
    id: str
    name: str
    # 取得: pursue を表明し前提を満たした場合の積算速度（tick数で100%に到達）
    acquisition_ticks: int = 18
    # 前提条件（全て満たす必要）。数値はNationStateのフィールドと比較
    prerequisites: dict = Field(
        default_factory=lambda: {"military": 40.0, "stability": 45.0})
    # 制度上の初期保有者（NPT的な「既存保有国」）
    initial_holders: list[str] = []
    # 効果パラメータ（エンジンの解決部が参照）
    deterrence_vs_nonholder: float = 0.15   # 非保有国が保有国に開戦する意欲の係数
    deterrence_mutual: float = 0.03         # 保有国同士の開戦意欲の係数（MAD）
    military_mult: float = 1.15             # 軍事力への直接倍率
    pursuit_cost_gdp: float = 0.002         # 追求中の毎tickの経済コスト
    abandon_stability_hit: float = 8.0      # 放棄時の国内安定打撃
    abandon_trust_gain: float = 6.0         # 放棄時のレジーム参加国からの信頼回復
    collective_sanction: bool = False       # 加盟国の制裁をレジーム全体へ伝播するか


CATALOG: list[FactorSpec] = [
    FactorSpec(
        id="nuclear",
        name="核兵器",
        acquisition_ticks=18,
        prerequisites={"military": 40.0, "stability": 45.0},
        initial_holders=[],            # プリセット側で指定（earth: 実情を反映）
    ),
    FactorSpec(
        id="export_control",
        name="輸出規制レジーム",
        acquisition_ticks=4,            # 加盟は早い（制度的参加）
        prerequisites={"stability": 40.0},
        initial_holders=[],
        collective_sanction=True,       # 加盟国の制裁は全加盟国へ伝播
        abandon_stability_hit=2.0,
        abandon_trust_gain=2.0,
    ),
]

FACTORS_BY_ID = {f.id: f for f in CATALOG}
