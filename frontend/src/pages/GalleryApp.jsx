// リプレイギャラリー(SPAのルート)。旧 独立index.html と同じ内容をReact化。
const C = { war: "#ff5252", peace: "#4ade80", sanction: "#ff8a3d", cyber: "#22d3ee" };

const CARDS_16 = [
  { href: "#/viewer?replay=replays/rl_earth_hormuz/replay.jsonl", tag: "エネルギー・シーレーン", title: "ホルムズ海峡封鎖",
    res: true, desc: <>エネルギー航路の途絶が価格と備蓄競争を伝播。<b className="res">RL世界では封鎖下で戦争1件が発生(ルールベース政策では0件)</b>。同じ介入でも政策の選択が分岐を作ります。</> },
  { href: "#/viewer?replay=replays/rl_earth_hormuz_if_t5/replay.jsonl", tag: "反実仮想(IF史)", title: "IF: ホルムズを1tick早く封鎖したら",
    res: true, desc: <>同じ世界・同じRL政策で介入だけt=6→t=5に前倒し。<b className="res">エネルギー価格は2.93→2.61に収まり、戦争は発生しなかった</b> — 介入時点1tickの差が帰結を分けました。</> },
  { href: "#/viewer?replay=replays/rl_earth_financial_crisis/replay.jsonl", tag: "金融・経済", title: "世界金融危機",
    res: true, desc: <>信用収縮が貿易効率を叩き、資源輸入国から順に不足イベントが連鎖。<b className="res">平均債務は116%と、ルールベース政策(96%)より深刻化</b> — 学習ポリシーの運営が別の危険を作っています。</> },
  { href: "#/viewer?replay=replays/rl_earth_taiwan/replay.jsonl", tag: "半導体・台湾有事", title: "台湾海峡の航路遮断",
    desc: <>半導体シーレンの途絶がチップ価格を急騰させ、軍事・生産の両面に伝播します。</> },
  { href: "#/viewer?replay=replays/rl_earth_jpn_taiwan/replay.jsonl", tag: "日本の安全保障", title: "日本の周辺情勢(米ハブ同盟網)",
    desc: <>日本を米国ハブの同盟網(日米・米韓・米豪・米台)に置いた設定で台湾有事を扱う、憲章の「現在の日本における安全保障リスク」の典型シナリオ。</> },
  { href: "#/viewer?replay=replays/rl_earth_disinfo_jpn/replay.jsonl", tag: "偽情報・ギャップチャネル", title: "対日偽情報キャンペーン",
    desc: <>平時の偽情報が慢性疑心を積み上げ、不足イベントを誘発する様子。慢性的な圧力が一発の事件と別の経路で効く「ギャップチャネル」のデモです。</> },
  { href: "#/viewer?replay=replays/rl_earth_triple_crisis/replay.jsonl", tag: "複合危機", title: "三重危機",
    desc: <>エネルギー・金融・食料のショックが同時にヒットする複合シナリオ。単一危機と伝播の重なり方が変わります。</> },
];

const CARDS_ALL = [
  { href: "#/viewer?replay=replays/rl_all_hormuz/replay.jsonl", tag: "全国家・シーレーン", title: "ホルムズ海峡封鎖(176カ国)",
    res: true, desc: <>同一の介入を176カ国世界で。<b className="res">戦争6件・崩壊1</b> — 16カ国版(戦争1)より連鎖の自由度が大きく、少数精鋭の世界では見えなかった波及が出ます。</> },
  { href: "#/viewer?replay=replays/rl_all_hormuz_if_t5/replay.jsonl", tag: "全国家・反実仮想", title: "IF: 全国家世界で1tick早く封鎖(176カ国)",
    res: true, desc: <><b className="res">封鎖前倒しで戦争6→4件</b>。16カ国版と同じ分岐実験を大世界で実行 — 介入時点の感度が国家数に対してどう変わるか比較できます。</> },
  { href: "#/viewer?replay=replays/rl_all_financial_crisis/replay.jsonl", tag: "全国家・金融", title: "世界金融危機(176カ国)",
    res: true, desc: <><b className="res">債務デフォルト7件</b>。金融伝播は貿易網の密度に効くので、176カ国では脆弱国の連鎖的破綻が16カ国版より際立ちます。</> },
  { href: "#/viewer?replay=replays/rl_all_taiwan/replay.jsonl", tag: "全国家・台湾有事", title: "台湾海峡の航路遮断(176カ国)",
    res: true, desc: <><b className="res">戦争2件・崩壊0</b>。半導体依存の国々に価格急騰が波及する様子を世界規模で追えます。</> },
];

import PageTitle from "../components/PageTitle";

const GH = "https://github.com/kjranyone/meta-security-hackathon-vol-2/blob/main";

export default function GalleryApp() {
  return (
    <div className="gallery">
      <PageTitle small="RL政策リプレイギャラリー" />
      <p className="sub">
        以下の全リプレイは、<b>全国家を強化学習ポリシー(汎用DeepPolicyNet 約50MB・教師LLMから蒸留)</b>で
        運用して生成したものです。ルールベースのHAND-coded政策ではありません — 各国の予算配分・軍事姿勢・
        配給・外交は毎tickニューラルネットの推論で決定されています。16カ国版と<b>176カ国の全国家版</b>を
        同一シナリオ・同一重みで並べてあります。
        地図は基本静的で、<b>事件が起きた瞬間だけ、その関係が発光する弧・リングとして浮かび上がり、約4秒で消えます</b>。
      </p>
      <p className="how">
        現段階の精度は低い(教師一致率0.91・macro-F1 0.73、模倣と生存は別目的であることを実測)。
        しかしこの訓練・配備パイプラインはAIが自律的に構築したものであり、計算資源と観測変数の定義を
        増やすことで深いインサイトに到達できるか、という問いへの足場です。
      </p>
      <p className="note">
        本シミュレーションは現実世界の予測装置ではありません。事案 → 機序 → 数値の経路を
        明示的に観察するための探索用具です(憲章と研究ログに主張の範囲を定義しています)。
        国防政策の意思決定に用いることはできません。
      </p>

      <div className="grid">
        {CARDS_16.map(c => <Card key={c.href} {...c} />)}
      </div>

      <h2 className="sec">全国家版 <small>176カ国・全てRL政策で運用(リプレイ1本約14MB・読込に数秒)</small></h2>
      <div className="grid">
        {CARDS_ALL.map(c => <Card key={c.href} {...c} />)}
      </div>

      <h2 className="sec">ライブ推論モード <small>ブラウザ内でエンジンと学習モデル1本がそのまま実行される(初回読込に時間がかかります)</small></h2>
      <div className="grid">
        <a className="card" href="#/live">
          <span className="tag">ブラウザ実行・ライブ</span>
          <h2>ライブ推論モード・ブラウザ実行</h2>
          <p>サーバ不要。このページ内で<b>本物のPythonエンジンと学習モデル1本(約50MB)が
          WASM(Pyodide)上で実行</b>されます — 力学の移植ではなく同一コードなので、
          ネイティブ実行と<b className="res">同seedで400tick・bit一致を検証済み</b>。
          シード/世界の差し替え、海峡封鎖・災害などの介入もすべてブラウザ内で完結。</p>
        </a>
      </div>

      <p className="foot">
        サーバ版ライブ推論モード(<a href="#/god">#/god</a> — PythonバックエンドとWebSocketで接続、
        リポジトリをクローンして <code>uv run uvicorn terrarium.server.app:app --port 8788</code>)。
        学習・評価の主張の範囲は
        <a href={`${GH}/README.md`}>README</a> ・
        <a href={`${GH}/CHARTER.md`}>CHARTER</a> ・
        <a href={`${GH}/report/research_log.md`}>研究ログ</a> を参照してください。
      </p>
    </div>
  );
}

function Card({ href, tag, title, desc }) {
  return (
    <a className="card" href={href}>
      <span className="tag">{tag}</span>
      <h2>{title}</h2>
      <p>{desc}</p>
    </a>
  );
}
