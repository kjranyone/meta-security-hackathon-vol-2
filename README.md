# Geopolitics Terrarium
**〜神の地政学とバタフライ・エフェクト〜**

第2回 AIエージェント社会シミュレーション・ハッカソン「メタ安全保障」（Singulab × AUTOMATA）応募作品。

**実世界地図上**の国家AIたちに対し、プレイヤーが「神」として海峡封鎖・偽情報投下・資源消滅などの介入を行い、**サプライチェーンの連鎖反応が世界をどう変えるか**を観測する非対称安全保障サンドボックスです。

> ⚠️ 本シミュレーションは公開されている概算データに基づく中立・分析目的のものです。特定の国・個人の標的化を意図するものではありません。地図データはNatural Earth（パブリックドメイン）を使用しています。

## コンセプト

- **神（プレイヤー）は国家を運営しない。** 介入カードと環境スライダーで世界の初期条件・パラメータを歪めるだけ
- 国家AI（現在: ルールベース / モックLLM、開発中: LLM+強化学習の複合戦略AI）が生存をかけた対応を行う
- **介入1件が連鎖（カスケード）を生み、どの介入点が何を変えるかを反実仮想（A/B）で計測できる**

例（実世界プリセット、ホルムズ海峡封鎖、seed=42, 36ヶ月）:

| 指標 | baseline | 封鎖シナリオ | 差分 |
|---|---|---|---|
| 世界GDP | 175.9 | 135.7 | **-22.9%** |
| エネルギー価格 | 1.00 | 1.50 | **+50%** |
| 半導体価格（電力不足→ファブ減産の連鎖） | 1.00 | 1.22 | **+22%** |
| 不足イベント数 | 326 | 434 | **+33%** |

台湾海峡封鎖はより軽微（GDP -5.9%）——ホルムズ（エネルギー動脈）と台湾（半導体）の**戦略的重要度の非対称性**がそのまま現れる。

## クイックスタート

要件: Python 3.10+ / [uv](https://docs.astral.sh/uv/)

```bash
cd server
uv sync --all-extras          # 依存インストール（初回のみ）
uv run pytest                 # 決定論テスト（同一seed=同一結果の検証含む）

# 実世界プリセットでシミュレーション（ヘッドレス）
uv run python -m terrarium.runner.headless \
    --preset earth --seed 42 --ticks 36 --policy mock_llm \
    --scenario scenarios/earth_hormuz.yaml

# 反実仮想A/B実験（baseline vs シナリオ、同seed・同世界）
uv run python -m terrarium.runner.ab \
    --preset earth --seed 42 --ticks 36 --policy mock_llm \
    --scenario scenarios/earth_hormuz.yaml
```

### リプレイビューア（実世界地図）

```bash
# リポジトリルートから静的サーバを起動
python3 -m http.server 8787
# ブラウザで開く（?replay= で自動読み込み）
open "http://localhost:8787/web/viewer.html?replay=http://localhost:8787/server/logs/earth_earth_hormuz/replay.jsonl"
```

Natural EarthのGeoJSONで実世界を描画: 国家の領土塗り（崩壊で暗転）・実在7海峡の⚓/⛔マーカー・
商品別の航路アーク（封鎖された航路は赤の破線）・戦争線・国家統計・価格チャート・イベントカスケードを
タイムライン scrub / 再生で確認できます。replay.jsonl のドラッグ＆ドロップにも対応。

### 世界の自動生成（プロシージャル生成）

実世界プリセット（`presets/earth.yaml`: 実在16主体・実在海峡・シーレーン）に加え、
シードから**需給バランスの取れた架空世界を実地図上に自動生成**できます。

```bash
# 架空国家を実地図の陸上に自動配置（実在海峡も利用）
uv run python -m terrarium.runner.genworld --seed 7 --nations 8

# 生成世界でシミュレーション（A/Bも --gen-seed を揃えれば同一世界で比較可能）
uv run python -m terrarium.runner.headless --gen-seed 7 --seed 42 --ticks 36 \
    --policy mock_llm --scenario scenarios/gen_chokepoint.yaml
```

生成器の性質（`src/terrarium/world/worldgen.py`）:
- **決定論**: 同じ `(seed, nations, chokepoints)` → 同じ世界（テスト担保）
- **需給バランス**: 全商品で世界供給 ≥ 需要×1.15になるよう資源ユニットを自動割当。神が介入しない限り経済は自然崩壊しない
- **8アーキタイプ**（資源専制国・穀物大国・半導体島国・金融ハブ・製造大国・新興国・資源小国・覇権国）から persona・色を生成。`--nations 12` のように増やすとアーキタイプを再利用
- 架空国家の重心は GeoJSON の**陸上ポリゴン内からサンプリング**（南極除外）、航路は実在海峡（ホルムズ・マラッカ・台湾海峡・スエズ等）経由で張られる
- シナリオでは国家・海峡を `#0`（ソート順インデックス）でも参照可能。生成世界でも汎用シナリオ（`scenarios/gen_*.yaml`）が動く

## アーキテクチャ

```
server/
  src/terrarium/
    world/     # 世界モデル（Pydantic: 国家・資源ユニット・実海峡の経緯度）、実地図世界生成
    sim/       # エンジン（生産→貿易→市場→消費→意思決定→外交→紛争→マクロ）
               # イベントソーシング（因果parentリンク付きJSONL）、神介入
    agents/    # policy層: heuristic / mock_llm / llm(z.ai OpenAI互換)
    runner/    # headless CLI / A/B反実仮想ランナー / 世界生成CLI
  presets/     # earth.yaml（実在16主体・実海峡・シーレーン）default.yaml（架空8国）gen_<seed>.yaml（自動生成）
  scenarios/   # 神の介入シナリオ（YAML、生成世界対応の #index 参照つき）
  logs/        # 実行結果（replay.jsonl / events.jsonl / series.csv / run.json）
  tests/       # 決定論・需給バランス・カオス伝播のテスト
web/
  viewer.html    # 実世界地図リプレイビューア（単一HTML、ビルド不要）
  world.geojson  # Natural Earth 110m admin-0（パブリックドメイン）
```

### 再現性の設計

- エンジンは完全決定論: `(seed, preset, policy, scenario)` が同じなら結果はbit等価（テストで担保）
- 全イベントは `events.jsonl` に parent ID 付きで記録 → **神の介入から崩壊・開戦への因果グラフ**を追跡可能
- リプレイはログ再生のみで再現（LLM再呼び出し不要）
- A/Bランナーは同seedで「介入あり/なし」を走らせ、指標系列のダイバージェンスとイベント数差分をレポート化

### 神の介入（実装済み）

| カード | 効果 |
|---|---|
| `close_chokepoint` | 海峡封鎖（期間指定可）。通過航路の輸送力が15%に |
| `open_chokepoint` | 封鎖解除 |
| `destroy_resource` | 国家の資源ユニット（油田/穀倉/ファブ）消滅 |
| `disaster` | 旱魃/地震/疫病 |
| `disinfo` | 偽情報投下（他国の信頼度低下・標的国の疑心暗鬼度上昇） |
| `set_param` | 国家の好戦性/疑心暗鬼度の強制書き換え |
| `global_slider` | 貿易効率・食料/エネルギー/チップ産出量などの世界パラメータ |

## LLM国家AI（開発中）

`--policy llm` で OpenAI 互換エンドポイント（デフォルト: z.ai coding plan / GLM）に国家ごとの意思決定を委譲します。

```bash
cp server/.env.example server/.env   # ZAI_API_KEY を設定
cd server && uv run python scripts/smoke_test_llm.py   # 接続テスト
```

- 各国家はpersona（技術立島国、資源専制国...）を持ち、情勢JSONを渡して政策JSON（予算配分・外交・軍事態勢）を返す
- 失敗時はheuristicにフォールバック。生応答はログ保存
- ロードマップ: LLM（戦略層）× 強化学習（戦術層）× ルール（世界解決層）の複合AI

## ロードマップ

- [x] M1: 決定論エンジン、イベントソーシング、A/B反実仮想、リプレイビューア
- [ ] M2: リアルタイム神介入UI（FastAPI + WebSocket）、LLM国家AI実戦接続
- [ ] M3: RL戦術層（小型MLPポリシー）、実データ風プリセット
- [ ] M4: 実験・チューニング、解析ノートブック、ドキュメント整備

## 開発

```bash
cd server
uv run pytest              # テスト
uv run pytest -q           # 簡易出力
```
