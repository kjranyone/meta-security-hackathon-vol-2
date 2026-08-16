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
| 世界GDP | 200.1 | 147.0 | **-26.5%** |
| エネルギー価格 | 1.00 | 1.50 | **+50%** |
| 半導体価格（電力不足→ファブ減産の連鎖） | 1.00 | 1.31 | **+31%** |
| 不足イベント数 | 326 | 490 | **+50%** |

台湾海峡封鎖はGDP -14.9%（地下資源の対日輸出も台湾海峡経由のため、以前より重く効く）。
三重危機（ホルムズ+台湾+スエズ封鎖）では GDP **-40.6%**・半導体価格 1.60・**戦争1件が勃発**する。

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
| `destroy_resource` | 国家の資源ユニット（油田/穀倉/ファブ/鉱床/軌道）消滅 |
| `create_resource` | **神が新たな資源を創り出す**（地下資源・宇宙インフラ含む、数量指定可） |
| `grant_tech` / `ban_tech` | 技術の授与 / 全世界での研究禁止 |
| `bailout` | **救済（ベイルアウト）**: 債務40%削減・信用回復 |
| `rate_hike` | **世界金利引き上げ**: 全債務国の利払いが急増（金融圧迫） |
| `disaster` | 旱魃/地震/疫病 |
| `disinfo` | 偽情報投下（他国の信頼度低下・標的国の疑心暗鬼度上昇） |
| `set_param` | 国家の好戦性/疑心暗鬼度の強制書き換え |
| `global_slider` | 貿易効率・各資源産出量などの世界パラメータ |

### 資源体系

| 資源 | 商品 | 備考 |
|---|---|---|
| oil / gas | エネルギー | 主要輸出国: サウジ・ロシア・豪・加・米 |
| grain | 食料 | 穀物地帯: 米・伯・露・豪・加・EU |
| fab | 半導体 | 電力と地下資源（鉱物）を必要とする。台湾・韓国が中心 |
| mineral | **地下資源**（レアアース/リチウム） | 中国が支配、新興国にも埋蔵。ファブの原料 |
| orbit | **宇宙資源**（軌道スロット/衛星） | 米・EU・中国のみ。**海峡を経由しない**（封鎖無効）が、喪失すると軍事力が漸減 |
| finance | （商品なし） | GDP成長ボーナス |

## 未来技術・宗教の創発（論文レベルの2026年以降）

シミュレーション内で時間が進む（1tick=1ヶ月、開始=2026年）と、**研究フロンティアの技術が「論文→原型→普及」していく**。各国の導入確率は研究吸収能力（GDP・金融・半導体備蓄）に比例し、**技術格差が創発的に生じる**。

| 分類 | 技術（創発時期） | 効果 |
|---|---|---|
| 兵器 | サイバー攻撃基盤(t5)・自律ドローン群(t8)・高出力レーザー迎撃(t14)・極超音速迎撃網(t22) | 軍事力増強、不信・好戦性上昇 |
| 製造 | AI設計ファブ(t10)・バイオ製造(t16)・自己修復自動工場(t26) | 商品生産の倍率向上 |
| 資源 | 深海底鉱業(t12)・**核融合(t20)**・宇宙太陽光(t24)・小惑星採掘(t30) | **油田ゼロの国にも電力を与える**（flat供給）、軌道価値上昇 |
| 宗教・社会 | **AI神格宗教(t15)**・テクノ・ナショナリズム(t18) | 安定・世論上昇、但是他国との信頼低下（イデオロギー摩擦） |

神の新カード: `grant_tech`（技術の授与）と `ban_tech`（全世界での研究禁止）。

**創発的な洞察（seed=42, 36ヶ月）**: ホルムズ封鎖のエネルギー価格は1.05にとどまる（t20以降に核融合・宇宙太陽光が普及し、**未来技術が海峡ショックを吸収**する）。一方 `earth_ban_fusion`シナリオで神が核融合を禁じてから封鎖するとエネルギー価格は**1.35**まで跳ね上がる — **未来エネルギー技術の禁止は海峡依存を固定化する**。未来予測と地政学の相互作用そのものを観測できる。

## 財政・金融システム（債務不履行と感染の連鎖）

国家は**債務（対GDP比）と信用**を持ち、毎月の財政収支（税収 vs 軍事費〔戦時2倍〕＋福祉＋利払い）で債務が蓄積する。債券金利は「基準2%＋信用リスクプレミアム（信用低下で最大+10%）＋インフレ連動＋**神の利上げ**」で決まり、**利払いが月利1.5%GDP超で確率的、3%超で確定的に債務不履行（sovereign_default）**となる。

デフォルトの効果: 通貨暴落（インフレ+15pt）・信用5%・債務半減（リストラ）・緊縮予算の強制 — そして**債権国（金融ハブ）が損失を被り信用が毀損（credibility_hit、因果parentリンク付き）→ 感染の火種**。再建モラトリアム（12ヶ月）で即死は防ぐ。

神の新カード: `bailout`（救済: 債務40%削減・信用回復）/ `rate_hike`（世界金利引き上げ＝全債務国への一斉圧迫）。

**金融感染の実測**（`earth_financial_crisis` = ホルムズ封鎖＋利上げ8%、seed=42）:
```
t7  日本 が債務不履行（利率10%）          ← 封鎖→輸入インフレ→金利上昇
t12 EU   が債務不履行（利率19%）          ← 日本債のcredibility_hitから感染
t20 日本 再び債務不履行（利率24%）
t22 米国 が債務不履行（利率13%）          ← 感染チェーンの終端
```
デフォルト計4件・世界GDP **-31.6%**。一方 `earth_bailout_or_contagion`（日本とエジプトを救済）は3件に抑制 — **「最後の貸し手」の介入効果がA/Bで測れる**。

## 複合戦略AI: LLM（戦略層）× 強化学習（戦術層）× ルール（世界解決層）

| 層 | 担当 | 実装 |
|---|---|---|
| **戦略層** | 外交・軍事姿勢・配給/プロパガンダ判断、自然言語の理屈 | LLM (z.ai/GLM, OpenAI互換) |
| **戦術層** | 毎月の予算配分（6プリセット）・姿勢・配給の微決定 | **強化学習** (numpy実装Actor-Critic, MLP) |
| **世界解決層** | 市場・物理・連鎖の決定論的解決 | ルールベース・エンジン |

RLは**DLフレームワーク非依存のnumpy実装**（Actor-Critic + Adam + エントロピー正則化）。依存軽量・CPUで高速・bit再現可能:

```bash
# 学習（例: 脆弱な新興国 SAH を旱魃ストレス下で2000エピソード）
uv run python -m terrarium.rl.train --preset default --nation SAH \
    --scenario scenarios/drought_sahelia.yaml --episodes 2000 --out models/rl_SAH_drought.npz

# 学習済み戦術層でシミュレーション
uv run python -m terrarium.runner.headless --preset default --policy rl \
    --rl-nation SAH --rl-weights models/rl_SAH_drought.npz --scenario scenarios/drought_sahelia.yaml

# ハイブリッド（LLM戦略 × RL戦術。ZAI_API_KEY必要）
uv run python -m terrarium.runner.headless --preset default --policy hybrid \
    --rl-nation VLT --scenario scenarios/chokepoint_closure.yaml

# 比較実験（heuristic vs RL vs hybrid、複数シード）
uv run python -m terrarium.runner.compare_policies --preset default --nation SAH \
    --scenario scenarios/drought_sahelia.yaml --seeds 5 --with-hybrid
```

**実測**（学習曲線は `models/*.curve.json`、重みは同梱）:
- 学習評価報酬: SAH（旱魃下）**-164.9 → -131.6 (+33.3)**、VLT **-4.3 → +7.2 (+11.5)** — 脆弱国家の生存戦略を獲得
- 36ヶ月の最終指標では手調整heuristicと**互角**（崩壊率0%を維持）— RLはドクトリンを書かずに同等性能へ到達
- ハイブリッド実走行の思考例: 「半導体を交渉カードにエネルギー供給源を分散確保。備蓄最優先の防衛態勢」（LLM戦略）×「予算=stockpile」（RL戦術）

### 自己対戦（マルチエージェントRL）

`--nation` にカンマ区切りを渡すと**複数国家の戦術層が同一世界内で同学習**します
（他方の学習者は自分の環境の一部 → 固定heuristic相手への過適合を避けた戦術の共進化）:

```bash
# 米中の戦術層をホルムズ封鎖下で自己対戦学習
uv run python -m terrarium.rl.train --preset earth --nation USA,CHN \
    --scenario scenarios/earth_hormuz.yaml --episodes 1500 --out models/selfplay_earth
# → models/selfplay_earth_USA.npz / _CHN.npz / selfplay_earth.curve.json

# 学習済み自己対戦ペアでシミュレーション（両国ともRL戦術）
uv run python -m terrarium.runner.headless --preset earth --policy rl \
    --rl-nation USA,CHN \
    --rl-weights models/selfplay_earth_USA.npz,models/selfplay_earth_CHN.npz \
    --scenario scenarios/earth_hormuz.yaml
```

### 実測: 自己対戦と「介入点の階層性」

- 自己対戦学習（2000エピソード、ホルムズ封鎖下）: **EGY +13.5 / JPN +0.5 / USA +0.1 / CHN +0.5** —
  脆弱な債務国ほど学習利得が大きく、資源豊富な大国は既に均衡近く（heuristicと同等）
- **報酬設計も介入点**: `--default-penalty`（自国デフォルトへの報酬ペナルティ）で
  「成長最適化」vs「債務規律」の目標を切り替えられる
- **正直な結果**（`earth_financial_crisis` 下、seed=42）: RL戦術層は予算ドクトリンを
  変える（heuristic: 福祉35/備蓄1・防御20ヶ月 → RL: 福祉36・中立36）が、
  債務252%+封鎖+利上げ8%という**構造的デフォルトは国内予算配分では防げず、
  連鎖は不変**（JPN t7 → EUR t12 → JPN t20 → USA t22）。
  連鎖を変えたのは**神のベイルアウト**（デフォルト4件→3件）—
  **戦術層（国家AI）・戦略層（LLM）・神（プレイヤー）の介入階層において、
  構造的危機を断てるのは神の介入のみ**という本作テーマの裏付けになった

## 神の玉座: リアルタイム介入UI（FastAPI + WebSocket）

ヘッドレス解析だけでなく、**プレイ中に神として介入できるライブUI**:

```bash
cd server && uv run uvicorn terrarium.server.app:app --port 8788
open http://localhost:8788/    # 👑 神の玉座
```

- 実世界地図がリアルタイムに描画され、tickごとのイベントがストリーミングされる
- **地図の海峡⚓をクリック** → 封鎖カード（6/12/24/60ヶ月・解除）
- **国家をクリック（または統計表の行）** → 介入カード: 偽情報・災害・好戦性/疑心暗鬼の書き換え・資源の創造/消滅・ベイルアウト・技術の授与
- 何も選んでいないときは**世界パラメータ**: 世界金利の利上げ・各資源産出スライダー・技術の全世界禁止
- 再生/一時停止/1tick進行/速度調整、世界の再創造（プリセット・policy・seed・生成世界・RL国家を指定可能）
- `--policy llm`（z.ai）でLLM国家AIがリアルタイム思考する様子を観察できる

### LLM戦略層の設定

```bash
cp server/.env.example server/.env   # ZAI_API_KEY を設定
cd server && uv run python scripts/smoke_test_llm.py   # 接続テスト
```

- 各国家はpersona（技術立島国、資源専制国...）を持ち、情勢JSON（自国状態・技術・他国関係を含む）を渡して政策JSON（外交・軍事態勢・配給）を返す
- 失敗時はheuristicにフォールバック。生応答はログ保存
- `--policy llm` で全国家LLM、`--policy hybrid` で対象国のみLLM×RL

## 解析パイプライン（図表生成）

`analysis/make_figures.py` がコミット済み実行ログ（`server/logs/*/`）から提出用図表を一括生成します:

```bash
cd server && uv run python ../analysis/make_figures.py
```

| 出力 | 内容 |
|---|---|
| `analysis/out/cascade_*.png` | **因果カスケードグラフ**: 神の介入・技術創発を根とし、parentリンクをBFS辿りして深さ方向に配置。色はイベント種（デフォルト=赤・戦争=橙・崩壊=黒・政策転換=青…） |
| `analysis/out/cascade_bar_*.png` | 介入別の**子孫イベント数**（どの介入が最も大きな連鎖を生んだか） |
| `analysis/out/ab_*.png` | **A/Bダイバージェンス**: baseline vs シナリオのGDP・価格・安定・不足イベント系列 |
| `analysis/out/sensitivity_matrix.png` + `.csv` | **介入点×指標の感度行列**（最終値の差分）。どの介入点がどの指標に効くか一望 |

## ロードマップ

- [x] M1: 決定論エンジン、イベントソーシング、A/B反実仮想、リプレイビューア
- [x] 実世界地図化（Natural Earth GeoJSON、実在海峡・シーレーン、地下・宇宙資源、未来技術創発）
- [x] 複合戦略AI（LLM戦略層 × RL戦術層、学習・比較実験基盤）
- [x] M2: リアルタイム神介入UI「神の玉座」（FastAPI + WebSocket）
- [x] 財政・金融システム（債務不履行・感染）、解析パイプライン（カスケードグラフ・感度行列）
- [ ] M3: 実データ風プリセットの精緻化、マルチ国同時RL（自己対戦）
- [ ] M4: 実験・チューニング、解析ノートブック、レポート・デモ動画

## 開発

```bash
cd server
uv run pytest              # テスト
uv run pytest -q           # 簡易出力
```
