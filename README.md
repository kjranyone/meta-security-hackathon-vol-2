# Geopolitics Terrarium
**〜神の地政学とバタフライ・エフェクト〜**

第2回 AIエージェント社会シミュレーション・ハッカソン「メタ安全保障」（Singulab × AUTOMATA）応募作品。

**実世界地図上**の国家AIたちに対し、プレイヤーが「神」として海峡封鎖・偽情報投下・資源消滅などの介入を行い、**サプライチェーンの連鎖反応が世界をどう変えるか**を観測する非対称安全保障サンドボックスです。

> ⚠️ 本シミュレーションは公開されている概算データに基づく中立・分析目的のものです。特定の国・個人の標的化を意図するものではありません。地図データはNatural Earth（パブリックドメイン）を使用しています。

## コンセプト

- **神（プレイヤー）は国家を運営しない。** 介入カードと環境スライダーで世界の初期条件・パラメータを歪めるだけ
- 国家AI（現在: ルールベース / モックLLM、開発中: LLM+強化学習の複合戦略AI）が生存をかけた対応を行う
- **介入1件が連鎖（カスケード）を生み、どの介入点が何を変えるかを反実仮想（A/B）で計測できる**

例（実世界プリセット、ホルムズ海峡封鎖、seed=42, 36tick、`server/logs/` の実ログ）:

| 指標 | baseline | 封鎖シナリオ | 差分 |
|---|---|---|---|
| 世界GDP | 184.1 | 150.7 | **-18.1%** |
| エネルギー価格 | 1.00 | 1.31 | **+31%** |
| 半導体価格（電力不足→ファブ減産の連鎖） | 1.00 | 1.08 | **+8%** |
| 不足イベント数 | 315 | 477 | **+51%** |

台湾海峡封鎖はGDP -10.8%（164.2）（地下資源の対日輸出も台湾海峡経由）。
三重危機（ホルムズ+台湾+スエズ封鎖）では GDP **-28.9%**（130.9）・デフォルト2件。

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
**各ペインはドラッグで拡大・縮小可能**（地図とサイド列の境界バー、統計/チャート/フィードの各境界バー。
ダブルクリックで初期サイズに戻る。地図canvasはサイズに合わせて再描画）。神の玉座UIも同様。

ゲームライクな表示:
- **地図上部に西暦カレンダー**（西暦2026年8月1日開始、**1tick=1時間**の高速世界時計。分は演出として再生中に進む）
- **友好度グラフ**: 国家間の信頼度を地図上の弧で表現（緑=高信頼/灰=中立/赤=敵対、太さ=関係の強さ）。
  国選択中はその国から全他国への星型、未選択時は主要な友好・対抗関係のみ
- **タイムラインマーカーと演出**: 破綻・開戦・価格急騰・神介入・GDP急落のtickに色付きマーカー。
  再生で跨ぐとタイムラインが発光し効果音が鳴る（🔊でミュート切替、イベント種別で音程が変わる）

### IF史モード — 「過去、●●年に△△していたら」

決定論エンジンなので、**記録済みの歴史を過去のtickまで巻き戻し、介入を1つ差し込んで再実行**できます。
分岐tickまでは元の歴史とbit等価、以降が新しい歴史になります（A/Bは「最初から介入あり/なし」、
IF史は「歴史の途中で書き換え」の反実仮想）。

```bash
# 例: 金融危機の歴史で「t6（日本のデフォルト直前）に救済していたら」
uv run python -m terrarium.runner.whatif \
    --base earth_earth_financial_crisis --tick 6 --iv bailout:nation=JPN
```

実測（`whatif.json` に機械可読な分岐レポート）:

```
IF: t6 で日本を救済していたら
歴史が分岐した最初のtick: t6
最終差分: GDP +26.3 / デフォルト -2 / 戦争 ±0
元の歴史でだけ起きた: t7 JPN破綻 → t12 EU破綻（感染）→ t20 JPN再破綻 → t22 米国破綻
IF世界で新たに起きた:   t9 JPN破綻（債務252%は一度の救済では足りず）・t31 JPN破綻
```

→ **救済は日本の破綻自体は防げなかったが、EU・米国への感染の連鎖を断ち切った**。
「最後の貸し手」の効果は破綻件数ではなく感染経路の遮断にある、という示唆が読み取れる。

**ビューアからも**（神サーバ経由で `http://localhost:8788/static/web/viewer.html?replay=...` を開き「⏪ IF史」）:
分岐tickと介入カードを選ぶと神サーバが再実行し、分岐レポートとIF世界のリプレイを返します。
`run.json` の `config` に元runの (preset, policy, scenario) が記録されるため、IFは自動で同じ条件下から分岐します
（LLM run は非決定論的なため mock_llm にフォールバック+警告）。

### 全国家AI化: earth_all プリセット（全世界176カ国）

`earth_all` は **Natural Earth の全特徴を1国1国家AIとして手続き生成**します。
主要66カ国は概算データ（GDP・軍事・債務・資源構造）のテーブルで詳細化し、
残る国も決定論的なデフォルトで初期化。需給は全体で需要×1.15以上になるよう
トップアップされ、航路（~660本）は実際の海峡を経由して自動生成されます。

```bash
uv run python -m terrarium.runner.headless --preset earth_all --seed 42 --ticks 12     --policy mock_llm --scenario scenarios/earth_hormuz.yaml
```

- 全主体がそれぞれ予算・外交・軍事姿勢を決定する「本当の世界シミュレーター」
- 176カ国×664航路でも **~70ms/tick**（リアルタイム再生可）
- 同じseedで常に同一の世界（決定論）。16カ国版 `earth` は提出実験の再現用に温存

**earth_allでの封鎖実験**（seed=42, 24tick, `logs/earth_all_*`）:

| 指標 | baseline | ホルムズ封鎖 | 差分 |
|---|---|---|---|
| 世界GDP | 1589.8 | 1420.7 | **-10.6%** |
| デフォルト | 5件 | **50件** | +45 |
| 平均失業率 | 4.5% | **8.7%** | +4.2pt |
| 崩壊国家 | 0 | **1（ソマリア）** | +1 |

176カ国世界では封鎖の金融感染が**途上国を中心に10倍のデフォルト波**を起こす
（16カ国版では見えなかった規模効果）。因子も創発: 規制48カ国・通貨ブロック48カ国・
核9カ国（抑止により大規模戦争0件）。

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
    runner/    # headless CLI / A/B反実仮想 / IF史 / 世界生成CLI
  presets/     # earth.yaml（実在16主体・実海峡・シーレーン）default.yaml（架空8国）gen_<seed>.yaml（自動生成）
  scenarios/   # 神の介入シナリオ（YAML、生成世界対応の #index 参照つき）
  logs/        # 実行結果（replay.jsonl / events.jsonl / series.csv / run.json）
  tests/       # 決定論・需給バランス・カオス伝播のテスト
frontend/      # UIソース（Vite + React）。コンポーネント/ロジックはここで共有
web/           # ビルド済み成果物（コミット済み → 利用者は npm 不要）
  god.html / viewer.html / assets/
  world.geojson  # Natural Earth 110m admin-0（パブリックドメイン）
```

### UIはReact（ビルド済み成果物コミット）

両UI（神の玉座・リプレイビューア）は `frontend/` の React + Vite ソースから
**`web/` へビルドした成果物をコミット**しています。利用者・審査員は
`npm install` なしでそのまま動かせます（従来の単一HTMLと同じURL）。

```bash
cd server && uv run uvicorn terrarium.server.app:app --port 8788   # バックエンド
cd frontend && npm install && npm run dev                          # HMR開発サーバ(5173)
#   → http://localhost:5173/            神の玉座（WS/APIは8788へ自動プロキシ）
#   → http://localhost:5173/viewer.html ビューア（?replay=/static/server/logs/<run>/replay.jsonl）

npm run build   # 変更を確定するとき: web/god.html + web/viewer.html + web/assets/（ハッシュ付き）を再生成してコミット
```

共有コンポーネント/ロジック（両UIで再利用）: 地図レンダラ（領土・航路・海峡・友好度グラフ）、
投影法、シミュレーション暦、価格チャート、効果音、スプリッター、日付バー、IF史パネル。

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

## 非決定戦略因子: 核保有のデータモデル（FactorSpec）

「核は保有国にしか許されない」「放棄も新規保有も戦略」のような**国家AIの自己選択で動く
離散的ケイパビリティ**は、`world/factors.py` のデータモデルで定義します（エンジン非依存）:

```python
FactorSpec(
    id="nuclear", name="核兵器",
    acquisition_ticks=18,               # pursue表明から取得までの期間
    prerequisites={"military": 40, "stability": 45},   # 取得の前提
    initial_holders=[...],              # NPT的な既存保有国（プリセットで指定）
    deterrence_vs_nonholder=0.15,       # 非保有国→保有国への開戦意欲係数
    deterrence_mutual=0.03,             # 保有国同士（MAD）
    military_mult=1.15, pursuit_cost_gdp=0.002,
    abandon_stability_hit=8.0, abandon_trust_gain=6.0,
)
```

運用のプロトコル（全policyで共通）:
- 国家AIは毎tick **`doctrines: {nuclear: pursue|hold|abandon}`** を意思決定に含める
  （heuristic=脅威/体制崩壊への反応、LLM=プロンプトで選択、RL=行動空間に拡張可能）
- エンジンは **取得進捗(0-100%)を積算**（前提を満たし追求した場合のみ）、100%で保有へ遷移し
  `factor_acquired` イベント（因果parent付き）、**3tick継続した放棄表明**で放棄し
  `factor_relinquished`（国内安定打撃+他保有国からの信頼回復）
- **抑止**: 保有国への開戦意欲は×0.15、保有国同士は×0.03（MAD）
- 神は `grant_factor`（既成事実化）も可能

現在4因子を実装済み（いずれもCATALOG定義のみで追加）:

| 因子 | 戦略的意思決定 | 効果 |
|---|---|---|
| `nuclear` 核兵器 | 脅威時にpursue（18tick） | 抑止（対非保有×0.15/相互×0.03）・軍事×1.15 |
| `nuclear_umbrella` 核傘 | **核保有国と同盟**で加入（2tick） | 保護国の抑止を**0.75×で継承**（拡大抑止） |
| `export_control` 輸出規制 | 制裁対象/大国/戦時が加盟（4tick） | **加盟国の制裁がレジーム全体へ伝播**（集団制裁） |
| `currency_bloc` 通貨ブロック | 大国・準備枯渇国が加盟（6tick） | **為替感応度半減・準備流出0.7×**（決済網） |

新しい因子（共通防衛条約、資源カルテル…）も **CATALOG に FactorSpec を1つ足すだけ**。
エンジン・UI・ログ・IF史は一切変更不要です。実測では、脅威を受け前提を満たした国が
約18tickで取得に至り（テスト担保）、これらの離散遷移もparentリンク付きで因果グラフに乗ります。

## 汎用戦術AI（全国家RL化）

**汎用戦術AI**（`generalist.npz`）: 全国家を学習者として巡回しつつ**重みを共有**して訓練した
単一ポリシー。どの国に載せても動くため、**学習AIを選ぶだけでLLM無しで全世界がRL駆動**になる
（個別学習済みのUSA/CHN/JPN/EGYは専用重み、残り全てに汎用重みを自動適用）。

```bash
uv run python -m terrarium.rl.train --preset earth --nation ALL     --scenario scenarios/earth_hormuz.yaml --episodes 960 --seed 3   # → models/generalist.npz
```


## リアリズム層: 人口・労働・財政投資・為替・経常・CO2

国家は以下の**構造パラメータ**（NationSpec、プリセットで指定）を持ち、毎tickの力学に効きます:

| パラメータ | 効果 |
|---|---|
| `population_growth` 年率人口成長 | 人口が動態変化（戦争で減少） |
| `education` 教育水準 0-1 | 技術吸収速度・支持率の底上げ |
| `gini` 所得不平等 | 0.40超で安定を継続的に蝕む |
| `energy_renew` 再生エネルギー比率 | CO2排出量を決める（核融合普及で実効0.50へ） |

毎tickの力学（決定論）:
- **失業率**: 生産ギャップ・戦争・財・サービス不足（レイオフ）で上昇、福祉予算で緩和。失業は成長・支持・安定を蝕む（スタグフレーションのチャネル）
- **インフラ指数**: 補助金予算シェアで蓄積（生産力倍率0.5-1.25）、戦争で毀損
- **為替**: インフレ差で調整、債務不履行で**30%暴落**。通貨安は輸入インフレを増幅
- **経常収支・外貨準備**: 航路フロー×価格で毎tick計上。準備<1ヶ月分で**外貨危機**（輸入絞り・スタグフレーション・イベント発火）
- **CO2**: 化石生産×(1−実効再生比率)が毎tick累積。全球CO2は食料収穫を最大15%毀損（気候チャネル）

実測（earth, seed=42, 36tick）: ホルムズ封鎖は平均失業率を **6.7%→7.1%**、核融合禁止歴史ではCO2累積 **+3.1%** と、 スタグーションと気候経路の両方に定量効果が出る。

## 未来技術・宗教の創発（論文レベルの2026年以降）

シミュレーション内で時間が進む（**1tick=1時間**のRTS風高速世界時計、開始=西暦2026年8月1日）と、**研究フロンティアの技術が「論文→原型→普及」していく**。各国の導入確率は研究吸収能力（GDP・金融・半導体備蓄）に比例し、**技術格差が創発的に生じる**。

| 分類 | 技術（創発時期） | 効果 |
|---|---|---|
| 兵器 | サイバー攻撃基盤(t5)・自律ドローン群(t8)・高出力レーザー迎撃(t14)・極超音速迎撃網(t22) | 軍事力増強、不信・好戦性上昇 |
| 製造 | AI設計ファブ(t10)・バイオ製造(t16)・自己修復自動工場(t26) | 商品生産の倍率向上 |
| 資源 | 深海底鉱業(t12)・**核融合(t20)**・宇宙太陽光(t24)・小惑星採掘(t30) | **油田ゼロの国にも電力を与える**（flat供給）、軌道価値上昇 |
| 宗教・社会 | **AI神格宗教(t15)**・テクノ・ナショナリズム(t18) | 安定・世論上昇、但是他国との信頼低下（イデオロギー摩擦） |

神の新カード: `grant_tech`（技術の授与）と `ban_tech`（全世界での研究禁止）。

**創発的な洞察（seed=42, 36tick、実ログ）**: 同じホルムズ封鎖履歴を分岐させて核融合だけを禁止すると（IF史 t1）、CO2累積排出は **603 → 619 (+2.8%)** 増え、日本の債務不履行は t21→t34 に遅延する — **未来エネルギー技術の創発は気候と債務経路の両方を変える**（決定論的な因果比較）。

## 財政・金融システム（債務不履行と感染の連鎖）

国家は**債務（対GDP比）と信用**を持ち、毎tickの財政収支（税収 vs 軍事費〔戦時2倍〕＋福祉＋利払い）で債務が蓄積する。債券金利は「基準2%＋信用リスクプレミアム（信用低下で最大+10%）＋インフレ連動＋**神の利上げ**」で決まり、**利払いが対GDP比1.5%/tick超で確率的、3%/tick超で確定的に債務不履行（sovereign_default）**となる。

デフォルトの効果: 通貨暴落（インフレ+15pt）・信用5%・債務半減（リストラ）・緊縮予算の強制 — そして**債権国（金融ハブ）が損失を被り信用が毀損（credibility_hit、因果parentリンク付き）→ 感染の火種**。再建モラトリアム（12tick）で即死は防ぐ。

神の新カード: `bailout`（救済: 債務40%削減・信用回復）/ `rate_hike`（世界金利引き上げ＝全債務国への一斉圧迫）。

**金融感染の実測**（`earth_financial_crisis` = ホルムズ封鎖＋利上げ8%、seed=42）:
```
t7  日本 が債務不履行（利率10%）          ← 封鎖→輸入インフレ→金利上昇
t12 EU   が債務不履行（利率19%）          ← 日本債のcredibility_hitから感染
t20 日本 再び債務不履行（利率26%）
t22 米国 が債務不履行（利率13%）          ← 感染チェーンの終端
```
デフォルト計4件・世界GDP **-31.9%**。一方 `earth_bailout_or_contagion`（日本とエジプトを救済）は3件に抑制（GDP -28.4%） — **「最後の貸し手」の介入効果がA/Bで測れる**。

## リッチ観測: 戦略推論には渡せるもの全部を渡す

国家AIの意思決定入力（`NationView`）は現在値のみならず、**利用可能な情報の全体**を含みます:

| 入力 | 内容 |
|---|---|
| 時系列トレンド | 各商品価格の t-1/3/6/12比、自国のGDP・安定・失業・債務・為替・準備の変化率、**信頼の変化（±3以上の相手上位）** |
| 世界情勢 | 世界GDPとt-12比、平均失業、全球CO2、進行中の戦争一覧、**核保有国リスト** |
| 貿易構造 | 商品別の輸入依存度、**海峡別の曝露（「エネルギーの80%がホルムズ経由」）**、主要供給国/顧客の構成 |
| 他国の観測可能な概要 | 信頼・同盟・戦争・制裁に加え GDP・軍事・安定・核保有（大世界では関連上位30カ国に圧縮） |
| 直前の自分の決定 | 前月の予算・姿勢・配給・doctrine — **無記憶なLLPに一種の記憶を供給** |
| イベント系列 | 直近16件を `t14: ...` と**tick付き**で（時間的文脈） |

実例（ホルムズ封鎖下の日本がt15に観測するもの）: エネルギー価格 **+42.5% (vs t12)**、自国GDP **-51.9%**、
失業 **+227%**、海峡曝露 ホルムズ0.80/マラッカ0.80/台湾0.60、直前の自分の決定（備蓄0.33・防衛姿勢・核追求）。
LLMはこれら全部をJSONプロンプトで受け取り、次月の戦略を推論します。
heuristicは既存の挙動を維持（コミット済み実験の再現性は不変 — 実測で系列bit等価を確認）。

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

**実測**（学習曲線は `models/*.curve.json`、重みは同梱。観測は41次元=状態26+トレンド15）:
- 学習評価報酬: SAH（旱魃下）**-172.3 → -137.4 (+34.9)**、VLT **-19.2 → +3.3 (+22.5)** — 脆弱国家の生存戦略を獲得
- 自己対戦: EGY（金融危機下）**-85.7 → -45.1 (+40.6)**、USA **+6.5 → +8.3**、CHN **-0.2 → +1.1**
- 36tickの最終指標では手調整heuristicと**互角**（崩壊率0%を維持）— RLはドクトリンを書かずに同等性能へ到達
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

- 自己対戦学習（トレンド観測込み）: **EGY +40.6 / JPN +3.6**（金融危機下）— 脆弱な債務国ほど学習利得が大きい
- **報酬設計も介入点**: `--default-penalty`（自国デフォルトへの報酬ペナルティ）で
  「成長最適化」vs「債務規律」の目標を切り替えられる
- **正直な結果**（`earth_financial_crisis` 下、seed=42）: RL戦術層は予算ドクトリンを
  変える（heuristic: 福祉35/備蓄1・防御20tick → RL: 福祉36・中立36）が、
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
- **地図の海峡⚓をクリック** → 封鎖カード（6/12/24/60時間・解除）
- **国家をクリック（または統計表の行）** → 介入カード: 偽情報・災害・好戦性/疑心暗鬼の書き換え・資源の創造/消滅・ベイルアウト・技術の授与
- 何も選んでいないときは**世界パラメータ**: 世界金利の利上げ・各資源産出スライダー・技術の全世界禁止
- **地図下部の神介入HUD**（シミュレーターゲーム風ボタン列）: 対象（選択中の国家/海峡）に向けて
  封鎖・救済・旱魃・偽情報・資源の創造/消滅・技術授与・好戦性の書換・利上げ・技術禁止をワンクリックで発火
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

提出物は `report/` にあります: **ビジュアルレポート** `slides.html`（10スライド、`slides.pdf` も同梱）、
解析ノートブック `analysis/terrarium_analysis.ipynb`（実行結果埋込済み）、
デモ動画台本 `report/demo_script.md`。

## ロードマップ

- [x] M1: 決定論エンジン、イベントソーシング、A/B反実仮想、リプレイビューア
- [x] 実世界地図化（Natural Earth GeoJSON、実在海峡・シーレーン、地下・宇宙資源、未来技術創発）
- [x] 複合戦略AI（LLM戦略層 × RL戦術層、学習・比較実験基盤）
- [x] M2: リアルタイム神介入UI「神の玉座」（FastAPI + WebSocket）
- [x] 財政・金融システム（債務不履行・感染）、解析パイプライン（カスケードグラフ・感度行列）
- [x] **IF史モード**（過去tickへの介入差し込みで歴史を分岐、UI/CLI両対応）
- [x] 自己対戦RL（マルチ国同時学習）、報酬設計ノブ（`--default-penalty`）
- [x] ビジュアルレポート・解析ノートブック・デモ台本（`report/`）
- [ ] M3: 実データ風プリセットの精緻化
- [ ] M4: 3分デモ動画の収録（締切8/30）

## 開発

```bash
cd server
uv run pytest              # テスト
uv run pytest -q           # 簡易出力
```
