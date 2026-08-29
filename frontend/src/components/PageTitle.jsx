import { useState } from "react";
import AboutModal from "./AboutModal";

// クリックで作品情報を開くページタイトル(全ページ共通の導線)。
// small: 各ページのサブタイトル(任意)
export default function PageTitle({ small }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <h1 onClick={() => setOpen(true)} style={{ cursor: "pointer" }}
          title="この作品について">
        Geopolitics Terrarium {small ? <small>{small}</small> : null}
      </h1>
      {open && <AboutModal onClose={() => setOpen(false)} />}
    </>
  );
}
