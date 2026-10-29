// The owner's day in the browser: invoice an order, issue it, print it, reconcile payments.
// Usage: node e2e/flow.cjs http://127.0.0.1:8811 OUT_DIR   (server with a fresh, empty folder)
const { chromium } = require('playwright');
const fs = require('fs');
const base = process.argv[2] || 'http://127.0.0.1:8811';
const out = process.argv[3] || 'flow';
fs.mkdirSync(out, { recursive: true });
const problems = [];
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  page.on('pageerror', (e) => problems.push('PAGEERROR ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') problems.push('CONSOLE ' + m.text()); });
  page.on('response', (r) => { if (r.status() >= 500) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  const shot = async (name, full = true) => { await page.screenshot({ path: `${out}/${name}.png`, fullPage: full }); console.log('shot', name); };

  await page.goto(base + '/');
  if (await page.locator('text=Beispiel-Firma einwerfen').count()) {
    await page.click('text=Beispiel-Firma einwerfen');
    await page.waitForURL(/wachsen/);
    await page.waitForURL(base + '/', { timeout: 120000 });
  }
  await page.waitForTimeout(400);
  await shot('01-heute');

  // the invoice list: payment state, sums, filters
  const invHref = await page.$$eval('.nav a[href^="/t/"]', (as) => (as.find((a) => /Rechnungen/.test(a.textContent)) || {}).getAttribute('href'));
  await page.goto(base + invHref);
  await shot('02-rechnungen');
  await page.goto(base + invHref + '?f_pay_state=offen');
  await shot('03-rechnungen-offen');

  // an order that waits for its invoice: "+ Rechnung"
  const plus = page.locator('a.btn.small', { hasText: '+ Rechnung' }).first();
  await page.goto(base + '/');
  if (await plus.count()) {
    await page.goto(base + (await plus.getAttribute('href')));
  } else {
    const ordHref = await page.$$eval('.nav a[href^="/t/"]', (as) => (as.find((a) => /Aufträge/.test(a.textContent)) || {}).getAttribute('href'));
    await page.goto(base + ordHref);
    const first = await page.$eval('#list-body tr[data-href]', (tr) => tr.dataset.href);
    await page.goto(base + first);
    await page.locator('a.btn', { hasText: '+ Rechnung' }).first().click();
  }
  await page.waitForLoadState('networkidle');
  await shot('04-rechnung-formular');
  const why = await page.textContent('#derive-why');
  console.log('derive:', (why || '').trim());
  await page.click('button[type=submit]');
  await page.waitForLoadState('networkidle');
  await shot('05-entwurf');

  // company details first, then issue
  const draftUrl = page.url().split('?')[0];
  await page.goto(base + '/firma?zurueck=' + encodeURIComponent(draftUrl.replace(base, '')));
  await shot('06-firmendaten');
  const fill = async (k, v) => { const el = page.locator(`#f_${k}`); if (!(await el.inputValue())) await el.fill(v); };
  await fill('name', 'Röstwerk Hafenbohne GmbH');
  await fill('street', 'Am Sandtorkai 12');
  await fill('zip', '20457');
  await fill('city', 'Hamburg');
  await fill('vat_id', 'DE123456789');
  await fill('iban', 'DE95 2005 0550 2461 5874 01');
  await fill('email', 'buero@hafenbohne.de');
  await fill('phone', '040 123456');
  await page.click('button[type=submit]');
  await page.waitForLoadState('networkidle');
  await shot('06b-entwurf-positionen');
  const probs = await page.$$eval('#ausstellen .notice li', (li) => li.map((x) => x.textContent.trim()));
  console.log('issue problems:', JSON.stringify(probs));
  const toCustomer = page.locator('#ausstellen a.to-customer');
  if (await toCustomer.count()) {
    // the customer's address is missing: added where it belongs, as the owner would
    const back = page.url();
    await toCustomer.first().click();
    await page.waitForLoadState('networkidle');
    await page.click('#edit-toggle');
    const field = async (label, v) => {
      const el = page.locator('.fact', { has: page.locator('dt', { hasText: new RegExp('^\\s*' + label) }) }).locator('.edit-mode input');
      if ((await el.count()) && !(await el.first().inputValue())) await el.first().fill(v);
    };
    await field('Straße', 'Deichstraße 7');
    await field('PLZ', '21614');
    await page.click('.edit-mode button[type=submit]');
    await page.waitForLoadState('networkidle');
    await shot('06c-kunde-anschrift');
    await page.goto(back);
    console.log('issue problems after:', JSON.stringify(await page.$$eval('#ausstellen .notice li', (li) => li.map((x) => x.textContent.trim()))));
  }
  await page.click('#ausstellen button.primary');
  await page.waitForTimeout(1500);
  await shot('07-ausgestellt');
  const pill = await page.textContent('.pagehead');
  console.log('issued:', /festgeschrieben/.test(pill), (await page.textContent('h1')).trim());

  // print and e-invoice
  const rid = page.url().split('/r/')[1].split('?')[0];
  await page.goto(`${base}/r/${rid}/druck`);
  await shot('08-druck');
  const stamp = await page.locator('.copy-stamp').count();
  console.log('archived print with copy stamp:', stamp);
  const x = await page.request.get(`${base}/r/${rid}/xrechnung`);
  const xml = await x.text();
  console.log('xrechnung:', x.status(), x.headers()['content-type'], xml.includes('urn:xeinkauf.de:kosit:xrechnung_3.0') ? 'XRechnung' : xml.slice(xml.indexOf('<p'), xml.indexOf('<p') + 260).replace(/\s+/g, ' '));
  fs.writeFileSync(`${out}/xrechnung.xml`, xml);

  // mark an overdue invoice as paid, with undo
  await page.goto(base + '/');
  const paid = page.locator('button:has-text("✓ bezahlt")').first();
  if (await paid.count()) {
    await paid.click();
    await page.waitForTimeout(1200);
    await shot('09-bezahlt-rueckgaengig', false);
    const undo = page.locator('.toast button:has-text("Rückgängig")');
    console.log('undo offered:', await undo.count());
  }

  // reconciliation with preview
  const recon = page.locator('a:has-text("Ansehen und übernehmen")').first();
  if (await recon.count()) {
    await recon.click();
    await page.waitForLoadState('networkidle');
    await shot('10-abgleich');
  }

  // a record with payments
  await page.goto(base + invHref + '?f_pay_state=bezahlt');
  const firstPaid = await page.$eval('#list-body tr[data-href]', (tr) => tr.dataset.href).catch(() => null);
  if (firstPaid) { await page.goto(base + firstPaid); await shot('11-rechnung-bezahlt'); }

  // phone
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  mobile.on('pageerror', (e) => problems.push('PAGEERROR mobile ' + e.message));
  await mobile.goto(base + '/');
  await mobile.screenshot({ path: `${out}/12-handy-heute.png`, fullPage: true });
  await mobile.goto(base + invHref);
  await mobile.screenshot({ path: `${out}/13-handy-liste.png`, fullPage: false });
  const sw = await mobile.evaluate(() => document.documentElement.scrollWidth);
  console.log('mobile scrollWidth', sw);
  await browser.close();
  console.log(problems.length ? 'PROBLEMS:\n' + problems.join('\n') : 'no problems');
})().catch((e) => { console.error(e); process.exit(1); });
