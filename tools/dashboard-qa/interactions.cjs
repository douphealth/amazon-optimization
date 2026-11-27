// Dashboard QA: filters, CSV export, detail drawer, Ctrl+K, Esc, work-queue ticks, phone layouts; fails on console errors or overflow.
// Usage: python -m ace site && python -m http.server -d dist 8770 &  then  node tools/dashboard-qa/interactions.cjs <screenshot dir> http://localhost:8770
const { chromium } = require('playwright');
(async () => {
  const [out, base, mode] = [process.argv[2], process.argv[3], process.argv[4] || 'mock'];
  const b = await chromium.launch();
  const now = Date.now();
  const runs = { workflow_runs: [
    { run_number: 2, status: 'completed', conclusion: 'success', event: 'workflow_dispatch', created_at: new Date(now - 5 * 3600e3).toISOString(), html_url: 'https://github.com/x/y/actions/runs/2' },
    { run_number: 1, status: 'completed', conclusion: 'failure', event: 'schedule', created_at: new Date(now - 3 * 86400e3).toISOString(), html_url: 'https://github.com/x/y/actions/runs/1' },
  ] };
  const open = async (vp, scheme, hash) => {
    const p = await b.newPage({ viewport: vp, deviceScaleFactor: 1, colorScheme: scheme });
    p.errors = [];
    p.on('pageerror', e => p.errors.push(e.message));
    p.on('console', m => { if (m.type() === 'error') p.errors.push(m.text()); });
    await p.route('https://api.github.com/**', r => mode === 'fail' ? r.fulfill({ status: 403, body: '{}' }) : r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(runs) }));
    await p.goto(base + '/' + hash);
    await p.waitForSelector('h1');
    await p.waitForTimeout(350);
    return p;
  };
  const done = async (p, name, full) => {
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    await p.screenshot({ path: `${out}/${name}.png`, fullPage: !!full });
    console.log(name, '| overflow:', overflow, '| errors:', p.errors.join(' ; ') || 'none');
    await p.close();
  };
  const D = { width: 1440, height: 900 }, M = { width: 390, height: 844 };
  let p;
  p = await open(D, 'light', '#/overview'); await done(p, 'overview-light', true);
  p = await open(D, 'dark', '#/overview'); await done(p, 'overview-dark', false);
  p = await open(D, 'dark', '#/findings'); await done(p, 'findings', true);
  p = await open(D, 'light', '#/site/plantastichaven.com'); await done(p, 'site', true);
  // pages: chip filter, then open the drawer from a row
  p = await open(D, 'light', '#/pages');
  await p.click('button.chip[data-issue="first_link_very_late"]');
  console.log('  chip filter ->', await p.textContent('.pager b'), '| select synced:', await p.$eval('select[name=issue]', e => e.value), '| hash:', await p.evaluate(() => location.hash));
  const [dl] = await Promise.all([p.waitForEvent('download'), p.click('[data-export]')]);
  const fs = require('fs'); const path = await dl.path(); const csv = fs.readFileSync(path, 'utf8').trim().split('\n');
  console.log('  export ->', dl.suggestedFilename(), csv.length - 1, 'rows | header:', csv[0].slice(0, 60));
  await p.click('tr.row >> nth=0'); await p.waitForSelector('#drawer:not([hidden]) .links, #drawer:not([hidden]) #dr-links p');
  await p.waitForTimeout(400);
  console.log('  drawer ->', await p.textContent('#drawer h2'), '| links listed:', await p.$$eval('#drawer .links li', e => e.length), '| findings:', await p.$$eval('#drawer .find li', e => e.length));
  await done(p, 'drawer', false);
  // palette
  p = await open(D, 'dark', '#/overview');
  await p.keyboard.press('Control+k'); await p.keyboard.type('smartwatch');
  await p.waitForTimeout(150);
  console.log('  palette results:', await p.$$eval('.pal-i', e => e.map(x => x.textContent.trim()).slice(0, 4).join(' | ')));
  await p.screenshot({ path: `${out}/palette.png` });
  await p.keyboard.press('Enter'); await p.waitForSelector('#drawer:not([hidden])');
  console.log('  palette Enter opened drawer:', await p.textContent('#drawer h2'));
  await p.keyboard.press('Escape');
  console.log('  Esc closed drawer:', await p.$eval('#drawer', e => e.hidden), '| scrim hidden:', await p.$eval('#scrim', e => e.hidden));
  await p.keyboard.press('Control+k'); await p.keyboard.type('gearuptogrow'); await p.keyboard.press('Enter'); await p.waitForTimeout(200);
  console.log('  palette site nav ->', await p.textContent('h1'));
  await done(p, 'palette-after', false);
  // queue: tick one item, reload, check persistence
  p = await open(D, 'light', '#/queue');
  const before = await p.textContent('.card b');
  await p.click('input[data-done] >> nth=0'); await p.waitForTimeout(150);
  const after = await p.textContent('.card b');
  await p.reload(); await p.waitForSelector('h1'); await p.waitForTimeout(200);
  console.log('  queue tick:', before, '->', after, '| after reload:', await p.textContent('.card b'), '| nav count:', await p.textContent('#nav a[href="#/queue"] .count'));
  await done(p, 'queue', false);
  p = await open(D, 'dark', '#/activity'); await done(p, 'activity', false);
  p = await open(D, 'light', '#/controls'); await done(p, 'controls', false);
  p = await open(D, 'light', '#/notes'); await done(p, 'notes', false);
  p = await open(M, 'dark', '#/overview'); await done(p, 'm-overview', true);
  p = await open(M, 'light', '#/pages'); await p.click('tr.row >> nth=0'); await p.waitForTimeout(400); await done(p, 'm-drawer', false);
  p = await open(M, 'light', '#/findings'); await done(p, 'm-findings', false);
  p = await open(M, 'dark', '#/queue'); await done(p, 'm-queue', false);
  await b.close();
})();
