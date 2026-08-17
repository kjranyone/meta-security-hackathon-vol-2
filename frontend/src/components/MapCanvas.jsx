import { useEffect, useRef } from "react";
import { renderMap } from "../lib/renderMap";
import { VIEW, fitView, clampView, zoomAt } from "../lib/projection";

// 地図canvas。ズーム(+/−/ホイール)・ドラッグパン・クリック選択。
// 国名ラベルは LABEL_SCALE 以上のズームでのみ表示（renderMap側で判定）。
export default function MapCanvas({ tick, geo, meta, selectedNation, selectedChokepoint,
                                    showRoutes = true, god = false, onMapClick }) {
  const wrapRef = useRef(null);
  const cvRef = useRef(null);
  const userView = useRef(false);   // ズーム/パン済みならリサイズで自動フィットしない
  const drag = useRef(null);

  useEffect(() => {
    const wrap = wrapRef.current, cv = cvRef.current;
    if (!wrap || !cv) return;
    const fit = () => {
      const box = wrap.getBoundingClientRect();
      const w = Math.max(320, Math.floor(box.width) - 8);
      const h = Math.max(240, Math.floor(box.height) - 8);
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      if (userView.current) clampView(cv);
      else fitView(cv);
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
    renderMap(cv.getContext("2d"), cv, tick,
              { geo, meta, selectedNation, selectedChokepoint, showRoutes });
  }

  function pos(ev) {
    const cv = cvRef.current;
    const rect = cv.getBoundingClientRect();
    return [(ev.clientX - rect.left) * (cv.width / rect.width),
            (ev.clientY - rect.top) * (cv.height / rect.height)];
  }

  function onPointerDown(ev) {
    const [mx, my] = pos(ev);
    drag.current = { mx, my, base: null, moved: false };
  }

  function onPointerMove(ev) {
    const d = drag.current;
    if (!d) return;
    const [mx, my] = pos(ev);
    const dx = mx - d.mx, dy = my - d.my;
    if (!d.moved && Math.abs(dx) + Math.abs(dy) < 5) return;
    const cv = cvRef.current;
    if (!d.moved) {
      d.moved = true;
      d.base = { ox: VIEW.ox, oy: VIEW.oy };
      cv.classList.add("dragging");
    }
    userView.current = true;
    VIEW.ox = d.base.ox + dx;
    VIEW.oy = d.base.oy + dy;
    clampView(cv);
    draw();
  }

  function endDrag(ev) {
    const d = drag.current;
    drag.current = null;
    cvRef.current?.classList.remove("dragging");
    if (!d || d.moved || !onMapClick) return;
    const [mx, my] = pos(ev);
    onMapClick(mx, my);
  }

  // ホイールズームは passive:false が必要なので手動登録
  useEffect(() => {
    const cv = cvRef.current;
    if (!cv) return;
    const onWheel = e => {
      e.preventDefault();
      const [mx, my] = pos(e);
      userView.current = true;
      zoomAt(cv, e.deltaY < 0 ? 1.08 : 1 / 1.08, mx, my);
      draw();
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    return () => cv.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick != null]);

  function zoomBtn(factor) {
    const cv = cvRef.current;
    if (!cv) return;
    userView.current = true;
    zoomAt(cv, factor);
    draw();
  }

  function fitBtn() {
    const cv = cvRef.current;
    if (!cv) return;
    userView.current = false;
    fitView(cv);
    draw();
  }

  if (!tick) return <div ref={wrapRef} className="mapwrap"><div className="drophint">—</div></div>;
  return (
    <div ref={wrapRef} className="mapwrap">
      <canvas ref={cvRef} className="map"
              onPointerDown={onPointerDown} onPointerMove={onPointerMove}
              onPointerUp={endDrag} onPointerLeave={() => {
                drag.current = null;
                cvRef.current?.classList.remove("dragging");
              }} />
      <div className="zoomctl">
        <button onClick={() => zoomBtn(1.25)}>+</button>
        <button onClick={() => zoomBtn(1 / 1.25)}>−</button>
        <button className="fit" onClick={fitBtn}>全体</button>
      </div>
    </div>
  );
}
