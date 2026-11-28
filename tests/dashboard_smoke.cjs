// Loads a built dashboard in a real browser and fails on any script error or a page that never
// leaves "Loading…". Run: node tests/dashboard_smoke.cjs <url>   (also run by tests/test_engine.py)
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(e.message));
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await p.route('https://api.github.com/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{"workflow_runs":[]}' }));
  for (const hash of ['', '#/queue', '#/findings', '#/pages', '#/activity', '#/notes', '#/controls']) {
    await p.goto(process.argv[2] + '/' + hash);
    await p.waitForSelector('h1', { timeout: 15000 }).catch(() => errors.push(`no heading on ${hash || 'overview'}`));
    const h1 = await p.textContent('h1').catch(() => '');
    if (/loading/i.test(h1 || '')) errors.push(`stuck loading on ${hash || 'overview'}`);
  }
  await b.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log('dashboard: every view loads without errors');
})();
