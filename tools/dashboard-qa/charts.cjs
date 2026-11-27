// Dashboard QA: search-clicks chart (tooltip, ticks, arrow keys, table view), filtered pages view, every route on desktop and phone.
// Usage: python -m ace site && python -m http.server -d dist 8770 &  then  node tools/dashboard-qa/charts.cjs <screenshot dir> http://localhost:8770
const { chromium } = require('playwright');
(async () => {
  const [out, base] = [process.argv[2], process.argv[3]];
  const b = await chromium.launch();
  const D = { width: 1440, height: 900 }, M = { width: 390, height: 844 };
  const open = async (vp, scheme, hash, dsf = 1) => {
    const p = await b.newPage({ viewport: vp, deviceScaleFactor: dsf, colorScheme: scheme });
    p.errors = [];
    p.on('pageerror', e => p.errors.push(e.message));
    p.on('console', m => { if (m.type() === 'error') p.errors.push(m.text()); });
    await p.route('https://api.github.com/**', r => r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ workflow_runs: [{ run_number: 3, status: 'completed', conclusion: 'success', event: 'workflow_dispatch', created_at: new Date(Date.now() - 3 * 3600e3).toISOString(), html_url: 'https://github.com/x/y/actions/runs/3' }] }) }));
    await p.goto(base + '/' + hash); await p.waitForSelector('h1'); await p.waitForTimeout(400);
    return p;
  };
  const report = async (p, name, full, shot = true) => {
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    if (shot) await p.screenshot({ path: `${out}/${name}.png`, fullPage: !!full });
    console.log(name, '| overflow:', overflow, '| errors:', p.errors.join(' ; ') || 'none');
    await p.close();
  };
  // tooltip on mouse hover
  let p = await open(D, 'light', '#/overview');
  const svg = await p.$('.chart svg'); const bb = await svg.boundingBox();
  await p.mouse.move(bb.x + bb.width * 0.5, bb.y + 100); await p.waitForTimeout(150);
  await p.mouse.move(bb.x + bb.width * 0.52, bb.y + 110); await p.waitForTimeout(150);
  console.log('hover tooltip visible:', await p.$eval('#tip', e => !e.hidden), '|', (await p.textContent('#tip')).slice(0, 80));
  console.log('y ticks:', await p.$$eval('.chart svg > text[text-anchor=end]', e => e.map(x => x.textContent).join(' ')));
  await p.focus('.chart'); for (let i = 0; i < 95; i++) await p.keyboard.press('ArrowLeft');
  const first = await p.$eval('.chart', e => e.dataset.at); await p.keyboard.press('ArrowRight');
  console.log('arrow keys: at first =', first, 'after right =', await p.$eval('.chart', e => e.dataset.at));
  await p.click('.numbers summary'); await p.waitForTimeout(100);
  console.log('numbers table, newest week:', (await p.textContent('.numbers tbody tr')).replace(/\s+/g, ' ').trim());
  await p.mouse.move(5, 5);
  await report(p, 'overview', true);
  p = await open(D, 'dark', '#/site/gearuptofit.com'); await report(p, 'site-gutf', true);
  p = await open(D, 'light', '#/pages?gidx=not&site=gearuptofit.com&visits=1'); console.log('GUTF not-in-Google pages with visitors:', await p.textContent('.pager b'));
  await p.click('tr.row >> nth=0'); await p.waitForTimeout(600); await report(p, 'drawer', false);
  p = await open(M, 'light', '#/pages'); await report(p, 'm-pages', false);
  p = await open(M, 'dark', '#/overview'); await report(p, 'm-overview', false);
  for (const h of ['#/queue', '#/findings', '#/activity', '#/controls', '#/notes', '#/site/plantastichaven.com', '#/site/frenchyfab.com']) {
    p = await open(D, 'light', h); await report(p, h.replace(/[#/]/g, '_'), false, false);
  }
  p = await open(D, 'light', '#/overview', 2); await p.screenshot({ path: `${out}/hi-overview.png` }); await p.close();
  p = await open(D, 'dark', '#/site/gearuptofit.com', 2); await p.screenshot({ path: `${out}/hi-site-gutf.png` }); await p.close();
  p = await open(D, 'light', '#/pages?gidx=not&site=gearuptofit.com&visits=1', 2); await p.click('tr.row >> nth=0'); await p.waitForTimeout(600); await p.screenshot({ path: `${out}/hi-drawer.png` }); await p.close();
  await b.close();
})();
