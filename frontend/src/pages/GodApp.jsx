import InterventionApp from "../components/InterventionApp";

// 介入モード(サーバ版): WebSocketでPythonバックエンド(8788)に接続
export default function GodApp() {
  return <InterventionApp mode="server" />;
}
