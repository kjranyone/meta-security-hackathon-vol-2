// クレジット表示(状態モーダル・ギャラリーのAboutで共用)
export default function Credits({ showPyodide }) {
  return (
    <>
      <h2 style={{ marginTop: 14 }}>クレジット</h2>
      <div className="statrows">
        <div className="statrow-line"><span>製作</span><b>Kojiro Tanaka (kjranyone)</b></div>
        <div className="statrow-line"><span>応募</span><b>第2回 AIエージェント社会シミュレーション・ハッカソン「メタ安全保障」</b></div>
        <div className="statrow-line"><span>地図データ</span><b>Natural Earth (public domain)</b></div>
        <div className="statrow-line"><span>学習教師</span><b>z.ai GLM</b></div>
        {showPyodide && (
          <div className="statrow-line"><span>実行基盤</span><b>Pyodide (CPython + numpy / WASM)</b></div>
        )}
      </div>
    </>
  );
}
