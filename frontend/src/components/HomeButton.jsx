// ギャラリー(タイトル)へ戻る。介入モードではWorkerの終了処理も
// ルータ側のunmountが担うため、ここは遷移だけ。
export default function HomeButton() {
  return (
    <button onClick={() => { location.hash = "/"; }}
            title="リプレイギャラリーへ戻る">タイトルに戻る</button>
  );
}
