import { useEffect, useState } from "react";
import GalleryApp from "./pages/GalleryApp";
import LiveApp from "./pages/LiveApp";
import GodApp from "./pages/GodApp";
import ViewerApp from "./pages/ViewerApp";

// 単一SPAのハッシュルータ。静的ホスティング(GitHub Pages)でも
// サーバ書き換え無しで /#/viewer?replay=... の深リンクが効く。
//   #/         ギャラリー(リプレイ+ライブへの導線)
//   #/viewer   リプレイビューア(?replay=&t=)
//   #/live     介入モード・ブラウザ実行(Pyodide)
//   #/god      介入モード・サーバ版(要バックエンド8788)
export function hashRoute() {
  const h = location.hash.replace(/^#/, "");
  const [path, query] = h.split("?");
  return { path: path || "/", query: new URLSearchParams(query || "") };
}

export default function App() {
  const [route, setRoute] = useState(hashRoute);
  useEffect(() => {
    const on = () => { setRoute(hashRoute()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  switch (route.path) {
    case "/viewer": return <ViewerApp key={route.query.toString()} params={route.query} />;
    case "/live": return <LiveApp />;
    case "/god": return <GodApp />;
    default: return <GalleryApp />;
  }
}
