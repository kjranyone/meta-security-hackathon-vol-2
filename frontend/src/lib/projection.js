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
