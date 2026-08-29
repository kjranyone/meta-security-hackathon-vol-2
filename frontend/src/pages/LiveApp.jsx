import InterventionApp from "../components/InterventionApp";

// ライブ推論モード(ブラウザ実行): Web Worker上のPyodideでエンジン+学習モデル1本を駆動
export default function LiveApp() {
  return <InterventionApp mode="browser" />;
}
