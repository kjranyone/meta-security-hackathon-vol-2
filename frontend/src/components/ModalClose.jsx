// モーダル右上の✕(標準的な閉導線。末尾ボタンがスクロール領域の外に
// 追い出される長いモーダルでも必ず見える位置に置く)
export default function ModalClose({ onClose }) {
  return (
    <button className="modalclose" onClick={onClose} aria-label="閉じる"
            title="閉じる">✕</button>
  );
}
