import { useEffect, useRef } from "react";
import { renderMap } from "../lib/renderMap";
import { fitView } from "../lib/projection";

// 地図canvas。propsが変わるたび再描画。wrapperのサイズに backing store を合わせる。
export default function MapCanvas({ tick, geo, meta, selectedNation, selectedChokepoint,
                                    showRoutes = true, god = false, onMapClick }) {
  const wrapRef = useRef(null);
  const cvRef = useRef(null);

  useEffect(() => {
    const wrap = wrapRef.current, cv = cvRef.current;
    if (!wrap || !cv) return;
    const fit = () => {
      const box = wrap.getBoundingClientRect();
      const w = Math.max(320, Math.floor(box.width) - 8);
      const h = Math.max(240, Math.floor(box.height) - 8);
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      fitView(cv);
      draw();
    };
    const ro = new ResizeObserver(fit);
    ro.observe(wrap);
    fit();
    return () => ro.disconnect();
    // canvas は tick 到着で後からマウントされるため、そのとき付け直す
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wrapRef, cvRef, tick != null]);

  useEffect(() => { draw(); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  function draw() {
    const cv = cvRef.current;
    if (!cv || !tick) return;
    const ctx = cv.getContext("2d");
    renderMap(ctx, cv, tick, { geo, meta, selectedNation, selectedChokepoint, showRoutes });
  }

  function handleClick(ev) {
    if (!onMapClick) return;
    const cv = cvRef.current;
    const rect = cv.getBoundingClientRect();
    const mx = (ev.clientX - rect.left) * (cv.width / rect.width);
    const my = (ev.clientY - rect.top) * (cv.height / rect.height);
    onMapClick(mx, my);
  }

  if (!tick) return <div ref={wrapRef} className="mapwrap"><div className="drophint">地図はシミュレーション開始後に表示されます</div></div>;
  return (
    <div ref={wrapRef} className="mapwrap">
      <canvas ref={cvRef} className={`map${god ? " god" : ""}`} onClick={handleClick} />
    </div>
  );
}
