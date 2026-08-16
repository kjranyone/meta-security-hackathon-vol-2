import { useState } from "react";

// ゲーム風ホバーツールチップ: <Tip title="見出し" text="説明"><button…/></Tip>
export default function Tip({ title, text, width = 250, children }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="tipwrap"
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}>
      {children}
      {open && (
        <span className="tipbox" style={{ width }} role="tooltip">
          <b>{title}</b><br />{text}
        </span>
      )}
    </span>
  );
}
