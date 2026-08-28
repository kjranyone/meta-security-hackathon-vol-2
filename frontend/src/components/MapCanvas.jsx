import { useEffect, useRef, useState } from "react";
import { renderMap } from "../lib/renderMap";
import { PULSE_TTL } from "../lib/pulses";
import { VIEW, fitView, clampVals, unprojectWith } from "../lib/projection";

const MIN_SCALE = 1.2, MAX_SCALE = 60;
// ホイール速度: 1ノッチ(deltaY≈±100)あたり約5%の指数カーブ（トラックパッドの連続deltaにも自然対応）
const WHEEL_K = 0.0005;
const EASE = 0.22;                    // フレーム毎の補間率（イージング）

// 地図canvas。Google Maps風のスムーズズーム（目標ビューへ補間）・ドラッグパン・クリック選択。
// pulses: イベント発光パルス({...,born})。到着時に減衰アニメーション(約4秒)を開始し、
// 全パルスが消えたら描画ループを止める(静穏時は静止地図のまま)。
export default function MapCanvas({ tick, geo, meta, selectedNation, selectedChokepoint,
                                    showRoutes = false, god = false, pulses = null,
                                    onMapClick, children }) {
  const wrapRef = useRef(null);
  const cvRef = useRef(null);
  const userView = useRef(false);   // ズーム/パン済みならリサイズで自動フィットしない
  const drag = useRef(null);
  const target = useRef(null);      // アニメーション目標 {scale, ox, oy}
  const raf = useRef(0);
  const pulseRef = useRef([]);
  const pulseRaf = useRef(0);
  const [zoomPct, setZoomPct] = useState(100);

  function updateZoomPct(cv) {
    const base = Math.min(cv.width / 366, cv.height / 186);
    setZoomPct(Math.round((VIEW.scale / base) * 100));
  }

  useEffect(() => {
    const wrap = wrapRef.current, cv = cvRef.current;
    if (!wrap || !cv) return;
    const fit = () => {
      const box = wrap.getBoundingClientRect();
      const w = Math.max(320, Math.floor(box.width) - 8);
      const h = Math.max(240, Math.floor(box.height) - 8);
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      if (!userView.current) fitView(cv);
      else if (!target.current) { const c = clampVals(cv, VIEW.scale, VIEW.ox, VIEW.oy); VIEW.ox = c.ox; VIEW.oy = c.oy; }
      updateZoomPct(cv);
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
  useEffect(() => () => { cancelAnimationFrame(raf.current); cancelAnimationFrame(pulseRaf.current); }, []);

  // イベントパルス: 到着時に蓄積し、減衰しきるまでrAFで再描画し続ける
  useEffect(() => {
    if (!pulses || !pulses.length) return;
    pulseRef.current = pulseRef.current.concat(pulses).slice(-800);
    if (!pulseRaf.current) {
      const step = () => {
        const now = Date.now();
        pulseRef.current = pulseRef.current.filter(p => now - p.born < PULSE_TTL);
        draw();
        pulseRaf.current = pulseRef.current.length ? requestAnimationFrame(step) : 0;
      };
      pulseRaf.current = requestAnimationFrame(step);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pulses]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  function draw() {
    const cv = cvRef.current;
    if (!cv || !tick) return;
    const now = Date.now();
    const aged = pulseRef.current.map(p => ({ ...p, age01: 1 - (now - p.born) / PULSE_TTL }));
    renderMap(cv.getContext("2d"), cv, tick,
              { geo, meta, selectedNation, selectedChokepoint, showRoutes,
                pulses: aged });
  }

  // 目標ビューへイージング補間（連続ホイールで目標を上書き=地図アプリの挙動）
  function animateTo(cv) {
    cancelAnimationFrame(raf.current);
    const step = () => {
      const t = target.current;
      if (!t) return;
      VIEW.scale += (t.scale - VIEW.scale) * EASE;
      VIEW.ox += (t.ox - VIEW.ox) * EASE;
      VIEW.oy += (t.oy - VIEW.oy) * EASE;
      const c = clampVals(cv, VIEW.scale, VIEW.ox, VIEW.oy);
      VIEW.ox = c.ox; VIEW.oy = c.oy;
      updateZoomPct(cv);
      draw();
      if (Math.abs(t.scale - VIEW.scale) > 0.003 ||
          Math.abs(t.ox - VIEW.ox) > 0.4 || Math.abs(t.oy - VIEW.oy) > 0.4) {
        raf.current = requestAnimationFrame(step);
      } else {
        VIEW.scale = t.scale; VIEW.ox = t.ox; VIEW.oy = t.oy;
        const c2 = clampVals(cv, VIEW.scale, VIEW.ox, VIEW.oy);
        VIEW.ox = c2.ox; VIEW.oy = c2.oy;
        updateZoomPct(cv);
        draw();
        target.current = null;
      }
    };
    raf.current = requestAnimationFrame(step);
  }

  // 現在の目標（無ければ実ビュー）を基準に、カーソル位置を固定した新しい目標を作る
  function retarget(cv, factor, mx = cv.width / 2, my = cv.height / 2) {
    const base = target.current || { scale: VIEW.scale, ox: VIEW.ox, oy: VIEW.oy };
    const [lon, lat] = unprojectWith(base, mx, my);
    const scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, base.scale * factor));
    const c = clampVals(cv, scale, mx - (lon + 180) * scale, my - (90 - lat) * scale);
    target.current = { scale, ox: c.ox, oy: c.oy };
    userView.current = true;
    animateTo(cv);
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
    target.current = null;             // パン中のズーム目標は破棄
    VIEW.ox = d.base.ox + dx;
    VIEW.oy = d.base.oy + dy;
    const c = clampVals(cv, VIEW.scale, VIEW.ox, VIEW.oy);
    VIEW.ox = c.ox; VIEW.oy = c.oy;
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

  // ホイールズーム（passive:falseでpreventDefault）
  useEffect(() => {
    const cv = cvRef.current;
    if (!cv) return;
    const onWheel = e => {
      e.preventDefault();
      const [mx, my] = pos(e);
      retarget(cv, Math.exp(-e.deltaY * WHEEL_K), mx, my);
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    return () => cv.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick != null]);

  function fitBtn() {
    const cv = cvRef.current;
    if (!cv) return;
    const base = Math.min(cv.width / 366, cv.height / 186);
    target.current = { scale: base,
                       ox: (cv.width - 360 * base) / 2,
                       oy: (cv.height - 180 * base) / 2 };
    userView.current = false;
    animateTo(cv);
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
        <button onClick={() => retarget(cvRef.current, 1.25)}>+</button>
        <button onClick={() => retarget(cvRef.current, 1 / 1.25)}>−</button>
        <button className="fit" onClick={fitBtn}>全体</button>
        <span className="zoompct">{zoomPct}%</span>
      </div>
      {children}
    </div>
  );
}
