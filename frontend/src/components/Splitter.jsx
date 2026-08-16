import { useRef } from "react";

// ドラッグで境界を動かすハンドル。onMove に画面座標(ev.clientX/Y)を渡す。
export function VSplit({ onMove, onReset, onEnd }) {
  const el = useRef(null);
  const down = e => {
    e.preventDefault();
    el.current.classList.add("drag");
    document.body.style.cursor = "col-resize";
    const move = ev => { ev.preventDefault(); onMove(ev); };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
      el.current.classList.remove("drag");
      onEnd?.();
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  };
  return <div ref={el} className="vsplit" onPointerDown={down} onDoubleClick={onReset}
              title="ドラッグで幅変更・ダブルクリックで戻す" />;
}

export function HSplit({ onMove, onReset, onEnd }) {
  const el = useRef(null);
  const down = e => {
    e.preventDefault();
    el.current.classList.add("drag");
    document.body.style.cursor = "row-resize";
    const move = ev => { ev.preventDefault(); onMove(ev); };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
      el.current.classList.remove("drag");
      onEnd?.();
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  };
  return <div ref={el} className="hsplit" onPointerDown={down} onDoubleClick={onReset}
              title="ドラッグで高さ変更・ダブルクリックで戻す" />;
}
