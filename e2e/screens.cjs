// Usage: node e2e/screens.cjs http://localhost:8765 OUT_DIR
const { chromium } = require('playwright');
const fs = require('fs');
const base = process.argv[2] || 'http://localhost:8765';
const out = process.argv[3] || 'screens';
fs.mkdirSync(out, { recursive: true });
(async () => {
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 1 });
const shot = async (name, full = true) => { await page.screenshot({ path: `${out}/${name}.png`, fullPage: full }); console.log('shot', name); };
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', m.text()); });
await page.goto(base + '/');
await shot('01-leer');
if (await page.locator('text=Beispiel-Firma einwerfen').count()) {
  await page.click('text=Beispiel-Firma einwerfen');
  await page.waitForURL(/wachsen/);
  await page.waitForTimeout(1200);
  await shot('02-wachsen', false);
  await page.waitForURL(base + '/', { timeout: 120000 });
}
await page.waitForTimeout(500);
await shot('03-heute');
await page.goto(base + '/organismus'); await page.waitForTimeout(400); await shot('04-organismus');
await page.goto(base + '/ablaeufe'); await shot('05-ablaeufe');
const nav = await page.$$eval('.nav a[href^="/t/"]', (as) => as.map((a) => a.getAttribute('href')));
console.log('nav', nav);
await page.goto(base + nav[0]); await shot('06-liste');
const first = await page.$eval('#list-body tr[data-href]', (tr) => tr.dataset.href);
await page.goto(base + first); await shot('07-datensatz');
await page.goto(base + '/fragen'); await shot('08-fragen');
await page.goto(base + '/quellen'); await shot('09-quellen');
await browser.close();

})().catch((e) => { console.error(e); process.exit(1); });
