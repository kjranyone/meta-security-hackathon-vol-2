// Equirectangular projection with a mutable view (set on canvas fit).
export const VIEW = { scale: 2.4, ox: 0, oy: 0 };
export function project(lon, lat) {
  return [VIEW.ox + (lon + 180) * VIEW.scale, VIEW.oy + (90 - lat) * VIEW.scale];
}
export function unproject(x, y) {
  return [(x - VIEW.ox) / VIEW.scale - 180, 90 - (y - VIEW.oy) / VIEW.scale];
}
export function fitView(cv) {
  VIEW.scale = Math.min(cv.width / 366, cv.height / 186);
  VIEW.ox = (cv.width - 360 * VIEW.scale) / 2;
  VIEW.oy = (cv.height - 180 * VIEW.scale) / 2;
}

// ズーム（カーソル位置の経緯度を固定）。factor>1で拡大
export function zoomAt(cv, factor, mx = cv.width / 2, my = cv.height / 2) {
  const [lon, lat] = unproject(mx, my);
  VIEW.scale = Math.max(1.2, Math.min(60, VIEW.scale * factor));
  VIEW.ox = mx - (lon + 180) * VIEW.scale;
  VIEW.oy = my - (90 - lat) * VIEW.scale;
  clampView(cv);
}

// 世界bbox外に余白が出ないようパンを制限（値計算版）
export function clampVals(cv, scale, ox, oy) {
  const w = 360 * scale, h = 180 * scale;
  return {
    ox: w <= cv.width ? (cv.width - w) / 2 : Math.min(0, Math.max(cv.width - w, ox)),
    oy: h <= cv.height ? (cv.height - h) / 2 : Math.min(0, Math.max(cv.height - h, oy)),
  };
}

export function clampView(cv) {
  const c = clampVals(cv, VIEW.scale, VIEW.ox, VIEW.oy);
  VIEW.ox = c.ox; VIEW.oy = c.oy;
}

// 任意のビューで座標→経緯度
export function unprojectWith(view, x, y) {
  return [(x - view.ox) / view.scale - 180, 90 - (y - view.oy) / view.scale];
}

export const LABEL_SCALE = 3.4;   // この倍率以上で国名ラベルを表示
