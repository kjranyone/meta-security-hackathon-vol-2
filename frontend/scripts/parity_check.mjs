// ブラウザ実行(Pyodide)がネイティブ基準値とbit一致するかを検証する。
//
//   node frontend/scripts/parity_check.mjs [--url http://localhost:8787/web/#/live]
//
// 事前要件:
//   - 静的配信(python3 -m http.server 8787 をリポジトリルートで)
//   - playwright-core が import 可能(npm i -D playwright-core 等で導入可)
//   - 基準値: server/tests/fixtures/parity_earth_seed42.json
//     (uv run --directory server python scripts/parity_fixture.py で再生成)
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(readFileSync(
  path.resolve(here, "../../server/tests/fixtures/parity_earth_seed42.json"), "utf8"));

const args = process.argv.slice(2);
const urlIdx = args.indexOf("--url");
const url = urlIdx >= 0 ? args[urlIdx + 1]
  : "http://localhost:8787/web/#/live";

let chromium;
try {
  ({ chromium } = require("playwright-core"));
} catch {
  console.error("playwright-core が見つかりません: npm i -D playwright-core を実行してください");
  process.exit(2);
}

const b = await chromium.launch({ channel: "chrome", headless: true });
const page = await b.newPage();
page.on("pageerror", e => console.error("PAGEERROR:", String(e).slice(0, 200)));
await page.goto(url, { waitUntil: "load", timeout: 60000 });
await page.waitForFunction(() => window.__liveSend, undefined, { timeout: 60000 });
// 起動オーバーレイ→(世界選択モーダル)。基準値のプロトコルはearth/seed42
// なので「軽量版16カ国=earth+停止状態で開く」を選んで進める
await page.waitForFunction(() =>
  Array.from(document.querySelectorAll(".modal")).some(m => m.textContent.includes("世界を選ぶ")),
  undefined, { timeout: 300000 });
await page.evaluate(() => {
  const m = Array.from(document.querySelectorAll(".modal")).find(m => m.textContent.includes("世界を選ぶ"));
  m.querySelectorAll(".radioopt")[1].click();   // 軽量版16カ国 = earth
  Array.from(m.querySelectorAll("button")).find(b => b.textContent.includes("停止状態で開く")).click();
});
await page.waitForFunction(() => !document.querySelector(".modal-back"), undefined, { timeout: 60000 });

await page.evaluate(() => { window.__lastRun = null; window.__liveSend({ cmd: "pause" }); });
await page.evaluate(() => window.__liveSend({ cmd: "run", ticks: 400 }));
await page.waitForFunction(() => window.__lastRun, undefined, { timeout: 600000 });
const metrics = await page.evaluate(() => window.__lastRun.metrics);
await b.close();

const a = JSON.stringify(metrics), e = JSON.stringify(fixture);
if (a === e) {
  console.log(`BIT-IDENTICAL: ${metrics.length} ticks (earth/seed42, 週次RL決定2回込み)`);
  process.exit(0);
}
console.error(`MISMATCH: browser ${metrics.length} ticks vs fixture ${fixture.length}`);
for (let i = 0; i < Math.max(metrics.length, fixture.length); i++) {
  const x = JSON.stringify(metrics[i]), y = JSON.stringify(fixture[i]);
  if (x !== y) { console.error(`first diff @tick ${i}:\n  browser: ${x}\n  fixture: ${y}`); break; }
}
process.exit(1);
