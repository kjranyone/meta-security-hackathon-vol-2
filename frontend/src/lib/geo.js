// Natural Earth GeoJSON loader with a module cache (same behavior as the
// original single-file pages: fetch("world.geojson") relative to /web/).
let cache = null;

export async function loadGeojson() {
  if (cache) return cache;
  // viewerは /web/ 配下なので相対で取れる。サーバの"/"からは /static/web/ にフォールバック
  let res = await fetch("world.geojson");
  if (!res.ok) res = await fetch("/static/web/world.geojson");
  const data = await res.json();
  const features = [];
  const byName = {};
  for (const f of data.features) {
    const admin = f.properties.ADMIN || f.properties.NAME || "";
    const rings = [];
    const g = f.geometry;
    if (!g) continue;
    if (g.type === "Polygon") rings.push(g.coordinates[0]);
    else if (g.type === "MultiPolygon") for (const p of g.coordinates) rings.push(p[0]);
    features.push({ admin, rings });
    if (!byName[admin]) byName[admin] = features.length - 1;
  }
  cache = { features, byName };
  return cache;
}
