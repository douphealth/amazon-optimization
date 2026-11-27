/* Commission Engine dashboard. Data comes from data.json and links.json (built by
   `python -m ace site`) plus one live call to GitHub for the engine's run status. No dependencies.
   Every number on screen comes from those sources; every button is a real link or a real action. */
(() => {
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = $("#view"), tip = $("#tip"), drawer = $("#drawer"), scrim = $("#scrim"), palette = $("#palette"), toastEl = $("#toast");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("en-US");
const num = n => (n == null ? "–" : nf.format(n));
const pct = x => (x == null ? "–" : Math.round(x * 100) + "%");
const signed = n => (n > 0 ? "+" : n < 0 ? "−" : "") + num(Math.abs(n));
const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : many || one + "s"}`;
const day = (iso, short) => {
  const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(iso || "");
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(short ? {} : { year: "numeric" }), timeZone: "UTC" }) : esc(iso || "–");
};
const ago = iso => {
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  return s < 90 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
};
const sum = (list, f) => list.reduce((a, x) => a + (f(x) || 0), 0);
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
function toast(text) {
  toastEl.textContent = text; toastEl.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (toastEl.hidden = true), 1800);
}
async function copy(text, done = "Copied") {
  try { await navigator.clipboard.writeText(text); toast(done); } catch { toast("Copying is blocked in this browser"); }
}

const SEVS = ["critical", "serious", "warning", "info", "good"];
const RANK = Object.fromEntries(SEVS.map((s, i) => [s, i]));
const SEV_LABEL = { critical: "Critical", serious: "Serious", warning: "Warning", info: "Note", good: "OK" };
const ICON = {
  critical: '<path d="M8.3 2h7.4L22 8.3v7.4L15.7 22H8.3L2 15.7V8.3z" fill="currentColor"/><path d="M12 7v6m0 3.5v.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>',
  serious: '<path d="M12 2.5 23 21H1z" fill="currentColor"/><path d="M12 9.5v5m0 3v.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>',
  warning: '<circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M12 7v6m0 3.5v.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>',
  good: '<circle cx="12" cy="12" r="10" fill="currentColor"/><path d="m7.5 12.5 3 3 6-6.5" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
  info: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 11v6m0-9.5v.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
};
const LINE = {
  overview: '<path d="M4 13h6V4H4zm10 7h6v-9h-6zM4 20h6v-4H4zM14 4v4h6V4z"/>',
  queue: '<path d="M4 6h16M4 12h10M4 18h6"/><path d="m16 16 2.5 2.5L22 14"/>',
  findings: '<path d="M5 21V4h11l-1.5 4L16 12H5"/>',
  pages: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  notes: '<path d="M5 4h14v16H5z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
  controls: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
  site: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  ext: '<path d="M14 5h5v5M19 5l-8 8M11 7H6v11h11v-5"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  play: '<path d="M7 5v14l12-7z"/>',
  bolt: '<path d="M13 3 5 14h6l-1 7 8-11h-6z"/>',
  dot: '<circle cx="12" cy="12" r="3.5" fill="currentColor" stroke="none"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  down: '<path d="M12 4v12m0 0-5-5m5 5 5-5M5 20h14"/>',
  theme: '<path d="M12 3a9 9 0 1 0 9 9A7 7 0 0 1 12 3z"/>',
};
const icon = (name, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${LINE[name] || LINE.dot}</svg>`;
const status = (sev, text) => `<span class="st ${sev}"><svg viewBox="0 0 24 24" aria-hidden="true">${ICON[sev] || ICON.info}</svg>${esc(text ?? SEV_LABEL[sev])}</span>`;
const ext = (href, text, cls = "btn") => `<a class="${cls}" href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}${icon("ext")}</a>`;
const tipAttr = html => `data-tip="${esc(html)}" tabindex="0"`;

const FIX_LABEL = {
  rel: "Marks Amazon links as sponsored (rel attribute).",
  blocked: "Repoints links that lead to a product marked wrong or gone.",
  box: "Adds a product box near the top of pages that have visitors and a late first link.",
  tags: "Adds or corrects the tracking ID on Amazon links.",
  disclosure: "Adds an affiliate disclosure where one is missing.",
};
const GROUPS = [["money", "Costs clicks or commission"], ["indexing", "Indexing"], ["search", "Search appearance"]];

let D, P, QUEUE, FIXED, BY, LINKS, QUERIES, RUNS = null;
const CHARTS = {};
let DONE = store.get("ace-queue-done", {});

/* ---------- data ---------- */
function prepare(data) {
  D = data;
  Object.values(D.issues).forEach(i => (i.label = i.label.charAt(0).toUpperCase() + i.label.slice(1)));
  P = D.pages.map(row => {
    const p = {};
    D.cols.forEach((c, i) => (p[c] = row[i]));
    p.s = D.sites[p.site];
    p.codes = (p.issues ? p.issues.split(" ") : []).sort((a, b) => RANK[issue(a).severity] - RANK[issue(b).severity]);
    try { const u = new URL(p.url); p.path = u.pathname + u.search; } catch { p.path = p.url; }
    p.sev = Math.min(4, ...p.codes.map(c => RANK[issue(c).severity] ?? 3));
    p.fix = p.codes.some(c => issue(c).to_fix);
    p.search = (p.gclicks || 0) + (p.bclicks || 0);
    p.visits = Math.max(p.sessions || 0, p.search);
    p.indexed = p.gverdict === "PASS";
    return p;
  });
  BY = new Map(P.map(p => [p.url, p]));
  QUEUE = P.filter(p => p.score > 0).sort((a, b) => b.score - a.score);
  FIXED = new Map(D.fixes.map(f => [f.url, f]));
  D.sites.forEach((s, i) => { s.worst = Math.min(4, ...P.filter(p => p.site === i && p.fix).map(p => p.sev)); });
}
const issue = code => D.issues[code] || { label: code.replace(/_/g, " "), severity: "info", action: "", group: "search" };
const gh = path => (D.repository ? `https://github.com/${D.repository}${path}` : "");
const slugOf = p => { try { return new URL(p.url).pathname.replace(/^\/|\/$/g, "").replace(/\//g, "__") || "home"; } catch { return "home"; } };
const handled = p => FIXED.get(p.url)?.status === "fixed" || !!DONE[p.url];

/* How a finding gets resolved on a given site: by the engine, or by hand. */
function handling(code, s) {
  const i = issue(code);
  if (i.severity === "info") return null;
  if (!i.fix) return { cls: "", text: "Manual", why: "The engine does not change this on its own." };
  if (s && !s.wordpress) return { cls: "", text: "Manual", why: "This site is not WordPress, so the engine cannot edit it." };
  if (!i.fix_on) return { cls: "", text: "Automatic fix off", why: `The "${i.fix}" fix exists but is switched off in sites.yaml.` };
  return i.fix === "box"
    ? { cls: "auto", text: "Automatic with visitors", why: `The engine adds a product box once the page has at least ${plural(D.box_min_clicks, "measured visit")}.` }
    : { cls: "auto", text: "Automatic", why: "The engine fixes this on its next run, on sites whose login secret exists." };
}
const handleChip = h => (h ? `<span class="chip ${h.cls}" ${tipAttr(esc(h.why))}>${h.cls ? icon("bolt") : ""}${esc(h.text)}</span>` : "");

/* ---------- routing ---------- */
function parse() {
  const raw = location.hash.replace(/^#\/?/, "") || "overview";
  const [path, query = ""] = raw.split("?");
  const [name, ...rest] = path.split("/");
  return { name, arg: decodeURIComponent(rest.join("/")), q: Object.fromEntries(new URLSearchParams(query)) };
}
const VIEWS = { overview, site, pages, queue, findings, activity, notes, controls };
const NAV = [["overview", "Overview"], ["queue", "Work queue"], ["findings", "Findings"], ["pages", "Pages"], ["activity", "Activity"], ["notes", "Notes"], ["controls", "Controls"]];

function nav(route) {
  const count = { queue: QUEUE.filter(p => !handled(p)).length, findings: Object.keys(D.issues).filter(c => issue(c).to_fix && total(c)).length, pages: P.length, activity: D.fixes.length };
  const item = (href, key, label, n, current, cls = "") =>
    `<a${cls ? ` class="${cls}"` : ""} href="#/${href}"${current ? ' aria-current="page"' : ""}>${icon(key)}<span>${esc(label)}</span>${n != null ? `<span class="count">${num(n)}</span>` : ""}</a>`;
  $("#nav").innerHTML = NAV.map(([k, l]) => item(k, k, l, count[k], route.name === k)).join("") + `<div class="nav-h">Sites</div>` +
    D.sites.map(s => item("site/" + s.domain, "site", s.name, s.to_fix || null, route.name === "site" && route.arg === s.domain, "nav-site")).join("");
}

function render() {
  const route = parse(), key = route.name + "/" + route.arg;
  nav(route);
  const fn = VIEWS[route.name] || overview;
  view.innerHTML = fn(route) || "";
  if (fn.after) fn.after(route);
  drawCharts();
  if (render.last !== key) { window.scrollTo(0, 0); view.classList.remove("fade"); void view.offsetWidth; view.classList.add("fade"); render.last = key; }
  document.title = ($("h1", view)?.textContent || "Overview") + " · Commission Engine";
  paintRuns();
}

/* ---------- building blocks ---------- */
const head = (title, sub, right = "", crumb = "") =>
  `<header class="head"><div>${crumb ? `<div class="crumb">${crumb}</div>` : ""}<h1>${esc(title)}</h1>${sub ? `<p class="sub">${sub}</p>` : ""}</div><div class="right">${right}</div></header>`;
const card = (title, body, sub = "", right = "") =>
  `<section class="card"><div class="hd"><h2>${esc(title)}</h2>${sub ? `<span class="muted">${sub}</span>` : ""}${right ? `<span class="right">${right}</span>` : ""}</div><div class="bd">${body}</div></section>`;

/* A sparkline needs at least three reports to say anything; before that the tile shows the change. */
function spark(points, label, unit = "reports") {
  if (!points || points.length < 3) return "";
  const v = points.map(pt => pt.v), lo = Math.min(...v), hi = Math.max(...v), W = 92, H = 30, span = hi - lo || 1;
  const xy = v.map((y, i) => [3 + i * (W - 6) / (v.length - 1), H - 4 - (y - lo) / span * (H - 8)]);
  const first = points[0], last = points[points.length - 1];
  return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)} over ${points.length} ${unit}" ${tipAttr(`<b>${esc(label)}</b><br>${day(first.d, 1)}: ${num(first.v)}<br>${day(last.d, 1)}: ${num(last.v)}`)}>
    <polyline points="${xy.map(pt => pt.map(n => n.toFixed(1)).join(",")).join(" ")}"/><circle cx="${xy[xy.length - 1][0].toFixed(1)}" cy="${xy[xy.length - 1][1].toFixed(1)}" r="3.5"/></svg>`;
}
const series = (history, key) => (history || []).map(h => ({ d: h.date, v: h[key] }));
function change(history, key) {
  if (!history || history.length < 2) return "";
  const d = history[history.length - 1][key] - history[history.length - 2][key];
  return d === 0 ? `No change since ${day(D.previous, 1)}` : `${signed(d)} since ${day(D.previous, 1)}`;
}
const tile = (label, value, note = "", sparkHtml = "") =>
  `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${value}</div>${sparkHtml}${note ? `<div class="delta">${note}</div>` : ""}</div>`;
const trendTile = (label, history, key, note) => tile(label, num(history?.length ? history[history.length - 1][key] : null), note || change(history, key), spark(series(history, key), label));

/* Ranked horizontal bars, one hue, value at the tip, hover detail. rows: [{name, value, href, open, note, tip}] */
function bars(rows, unit) {
  const max = Math.max(1, ...rows.map(r => r.value));
  return `<div class="bars" role="list">${rows.map(r => {
    const name = (r.open ? `<a href="#" data-open="${esc(r.open)}">${esc(r.name)}</a>` : r.href ? `<a href="${esc(r.href)}">${esc(r.name)}</a>` : esc(r.name)) + (r.note ? `<small>${esc(r.note)}</small>` : "");
    return `<div class="name" role="listitem">${name}</div>
      <div class="track${r.value ? "" : " zero"}" ${tipAttr(`<b>${esc(r.name)}</b><br>${num(r.value)} ${esc(unit)}${r.tip ? "<br>" + esc(r.tip) : ""}`)}><span class="fill" style="width:${(r.value / max * 100).toFixed(1)}%"></span></div>
      <div class="val">${num(r.value)}</div>`;
  }).join("")}</div>`;
}
function split(s) {
  const none = s.ok - s.with_links, all = Math.max(1, s.ok);
  const seg = (cls, n, label) => (n ? `<i class="${cls}" style="width:${(n / all * 100).toFixed(2)}%" ${tipAttr(`<b>${esc(s.name)}</b><br>${plural(n, "page")} ${label}`)}></i>` : "");
  return `<div class="seg" role="img" aria-label="${s.early} pages with an early Amazon link, ${s.late} with a late one, ${none} with none">${seg("a", s.early, "with a link near the top")}${seg("b", s.late, "with a late first link")}${seg("c", none, "without Amazon links")}</div>`;
}
const LEGEND = `<div class="legend"><span><i style="background:var(--data-1)"></i>Amazon link near the top</span><span><i style="background:var(--data-2)"></i>First link late</span><span><i style="background:var(--data-0)"></i>No Amazon links</span></div>`;
const siteHealth = s => (s.to_fix ? status(SEVS[s.worst], `${plural(s.to_fix, "page")} to fix`) : status("good", "Nothing to fix"));

/* Portfolio totals for a finding, now and in the previous report (same sites on both sides). */
const total = code => sum(D.sites, s => s.issues[code]);
function trend(code, sites = D.sites) {
  const both = sites.filter(s => s.prev);
  return both.length ? { now: sum(both, s => s.issues[code]), was: sum(both, s => s.prev.issues[code]) } : null;
}

/* ---------- engine status (live from GitHub; the repository must be public) ---------- */
function loadRuns() {
  if (!D.repository) return;
  if (D.repository_public === false) { RUNS = "private"; paintRuns(); return; }  // the browser could never read it
  fetch(`https://api.github.com/repos/${D.repository}/actions/workflows/weekly-audit.yml/runs?per_page=6`, { headers: { Accept: "application/vnd.github+json" } })
    .then(r => (r.ok ? r.json() : Promise.reject(new Error(r.status === 404 ? "private" : "unavailable"))))
    .then(j => { RUNS = j.workflow_runs || []; })
    .catch(e => { RUNS = e.message === "private" ? "private" : "unavailable"; })
    .finally(() => { paintRuns(); nav(parse()); });
}
function runState(r) {
  if (r.status !== "completed") return ["info", r.status === "queued" ? "Queued" : "Running now"];
  if (r.conclusion === "partial") return ["warning", `Finished; ${r.failed.join(", ")} failed`];
  return { success: ["good", "Succeeded"], failure: ["critical", "Failed"], cancelled: ["warning", "Cancelled"], timed_out: ["critical", "Timed out"] }[r.conclusion] || ["warning", r.conclusion || "Finished"];
}
function nextRun() {
  const m = /^(\d+) (\d+) \* \* (\d)$/.exec(D.schedule || "");
  if (!m) return null;
  const now = new Date(), d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), +m[2], +m[1]));
  while (d <= now || d.getUTCDay() !== +m[3] % 7) d.setUTCDate(d.getUTCDate() + 1);
  return d;
}
const when = d => d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
/* The run the repository recorded itself (data/last-run.json), shaped like a GitHub run. */
function recordedRun() {
  const r = D.last_run;
  if (!r) return null;
  const failed = ["audit", "pull", "rank", "fix", "submit"].filter(k => r[k] === "failure" || r[k] === "cancelled");
  return { run_number: r.run_number, html_url: r.url, created_at: r.finished, event: r.event, status: "completed",
           conclusion: failed.length ? "partial" : "success", recorded: true, failed };
}
function paintRuns() {
  const latest = Array.isArray(RUNS) && RUNS.length ? RUNS[0] : recordedRun();
  const st = latest ? runState(latest) : null;
  $("#run-pill").innerHTML = latest ? `<a class="pill" href="${esc(latest.html_url)}" target="_blank" rel="noopener">${status(st[0], "Last run " + st[1].toLowerCase())}<span class="muted">${ago(latest.created_at)}</span></a>` : "";
  $$("[data-run-latest]").forEach(el => {
    el.innerHTML = RUNS === null ? `<span class="muted">Checking GitHub…</span>`
      : latest ? `${status(st[0], st[1])}<a href="${esc(latest.html_url)}" target="_blank" rel="noopener">${ago(latest.created_at)}</a>`
      : `<span class="muted">${RUNS === "unavailable" ? "GitHub is not answering right now" : RUNS === "private" ? "No run recorded yet" : "No run yet"}</span>`;
    if (RUNS !== null && latest && latest.recorded) el.insertAdjacentHTML("beforeend", `<span class="muted small">as recorded by the run</span>`);
  });
  $$("[data-run-list]").forEach(el => {
    const rec = recordedRun();
    el.innerHTML = RUNS === null ? `<p class="muted">Checking GitHub…</p>`
      : !Array.isArray(RUNS) ? `<p class="muted">${rec ? `Last recorded run: <a href="${esc(rec.html_url)}" target="_blank" rel="noopener">#${esc(rec.run_number)}</a>, ${ago(rec.created_at)} (${esc(runState(rec)[1])}). ` : ""}${RUNS === "private" ? "The full run list is on GitHub; this page cannot read it while the repository is private." : "GitHub is not answering right now (often its hourly limit for anonymous requests); the full run list is on GitHub."} ${ext(gh("/actions"), "Open run history", "")}</p>`
      : !RUNS.length ? `<p class="muted">The engine has not run on GitHub yet.</p>`
      : `<div class="scroll"><table><thead><tr><th>Run</th><th>Started</th><th>Trigger</th><th>Result</th></tr></thead><tbody>${RUNS.map(r => {
          const s = runState(r);
          return `<tr><td><a href="${esc(r.html_url)}" target="_blank" rel="noopener">#${r.run_number}</a></td><td>${esc(when(new Date(r.created_at)))}<span class="sub">${ago(r.created_at)}</span></td><td>${r.event === "schedule" ? "Weekly schedule" : r.event === "workflow_dispatch" ? "Started by hand" : esc(r.event)}</td><td>${status(s[0], s[1])}</td></tr>`;
        }).join("")}</tbody></table></div>`;
  });
}

/* ---------- search clicks per day: Google and Bing ---------- */
const ENGINES = [["google", "Google", "var(--data-1)"], ["bing", "Bing", "var(--data-2)"]];
const COVERAGE_SHORT = {
  "Submitted and indexed": "Indexed", "Indexed, not submitted in sitemap": "Indexed, not in sitemap",
  "Crawled - currently not indexed": "Crawled, not indexed", "Discovered - currently not indexed": "Discovered, not indexed",
  "URL is unknown to Google": "Unknown to Google", "Duplicate, Google chose different canonical than user": "Google chose other canonical",
  "Duplicate without user-selected canonical": "Duplicate, no canonical", "Alternate page with proper canonical tag": "Alternate (canonical)",
};
const coverageShort = c => COVERAGE_SHORT[c] || c || "Not inspected";
const indexChip = p => (!p.gidx ? `<span class="muted small">Not inspected</span>` : p.gverdict === "ERROR" ? status("info", "Check failed")
  : status(p.indexed ? "good" : p.codes.includes("demand_page_not_in_google") ? "serious" : "warning", coverageShort(p.gidx)));
/* Weekly sums ending on the last day every engine with data has reported, so the newest week
   compares like with like. A week with a missing day is left out rather than undercounted. */
function weekly(tr, key) {
  const lastOf = k => tr[k].reduce((last, v, i) => (v == null ? last : i), -1);
  const engines = ENGINES.map(([k]) => k).filter(k => lastOf(k) >= 0);
  const stop = Math.min(...engines.map(lastOf)) + 1;
  const out = [];
  for (let end = stop; end >= 7; end -= 7) {
    const vals = tr[key].slice(end - 7, end);
    if (vals.every(v => v != null)) out.unshift({ d: tr.dates[end - 1], v: vals.reduce((a, b) => a + b, 0) });
  }
  return out;
}
function trendCard(id, tr, title, sub) {
  if (!tr || !tr.dates || !tr.dates.length) return "";
  CHARTS[id] = tr;
  const has = ENGINES.filter(([k]) => tr[k].some(v => v != null));
  const weeks = weekly(tr, "google").map((w, i) => ({ d: w.d, g: w.v, b: weekly(tr, "bing")[i]?.v }));
  const legend = `<div class="legend">${has.map(([, name, color]) => `<span><i style="background:${color}"></i>${name}</span>`).join("")}</div>`;
  const tableHtml = `<details class="numbers"><summary>Show the numbers</summary><div class="scroll" style="margin-top:10px"><table><thead><tr><th>Week ending</th>${has.map(([, n]) => `<th class="n">${n} clicks</th>`).join("")}</tr></thead><tbody>${
    weekly(tr, has[0][0]).map((w, i) => `<tr><td>${day(w.d)}</td>${has.map(([k]) => `<td class="n">${num(weekly(tr, k)[i]?.v)}</td>`).join("")}</tr>`).reverse().join("")}</tbody></table></div></details>`;
  return card(title, `<div class="chart" data-chart="${esc(id)}" tabindex="0" role="img" aria-label="${esc(title)}: daily clicks from ${has.map(e => e[1]).join(" and ")} over ${tr.dates.length} days"></div>${tableHtml}`, sub, legend);
}
function niceMax(v) {
  const raw = Math.max(1, v / 4), p = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / p;
  const step = Math.max(1, (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p);
  return step * 4;
}
function drawCharts() {
  $$(".chart[data-chart]", view).forEach(el => {
    const tr = CHARTS[el.dataset.chart];
    if (!tr) return;
    const W = Math.max(280, el.clientWidth), H = 230, L = 40, R = 64, T = 14, B = 26, iw = W - L - R, ih = H - T - B;
    const has = ENGINES.filter(([k]) => tr[k].some(v => v != null));
    const max = niceMax(Math.max(1, ...has.flatMap(([k]) => tr[k].filter(v => v != null))));
    const n = tr.dates.length, x = i => L + (n < 2 ? 0 : i * iw / (n - 1)), y = v => T + ih - v / max * ih;
    const grid = [0, 0.25, 0.5, 0.75, 1].map(f => `<line x1="${L}" x2="${L + iw}" y1="${y(max * f).toFixed(1)}" y2="${y(max * f).toFixed(1)}" class="g${f ? "" : " base"}"/><text x="${L - 8}" y="${(y(max * f) + 4).toFixed(1)}" text-anchor="end">${num(max * f)}</text>`).join("");
    const ticks = tr.dates.map((d, i) => d.endsWith("-01") ? `<text x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="middle">${new Date(d + "T00:00:00Z").toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" })}</text><line x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${T + ih}" y2="${T + ih + 4}" class="g"/>` : "").join("");
    const path = k => {
      let d = "", pen = false;
      tr[k].forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
      return d;
    };
    const ends = has.map(([k, name, color]) => {
      const i = tr[k].map((v, j) => (v == null ? -1 : j)).filter(j => j >= 0).pop();
      return { k, name, color, i, v: tr[k][i], ty: y(tr[k][i]) };
    }).sort((a, b) => a.ty - b.ty);
    for (let j = 1; j < ends.length; j++) if (ends[j].ty - ends[j - 1].ty < 15) ends[j].ty = ends[j - 1].ty + 15;
    el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${grid}${ticks}
      ${has.map(([k, , color]) => `<path d="${path(k)}" stroke="${color}" class="ln"/>`).join("")}
      ${ends.map(e => `<circle cx="${x(e.i).toFixed(1)}" cy="${y(e.v).toFixed(1)}" r="3.5" fill="${e.color}" class="end"/><text x="${(x(e.i) + 8).toFixed(1)}" y="${(e.ty + 4).toFixed(1)}" class="lbl">${e.name} ${num(e.v)}</text>`).join("")}
      <line class="xh" x1="0" x2="0" y1="${T}" y2="${T + ih}" visibility="hidden"/>
      ${has.map(([k, , color]) => `<circle class="hov" data-k="${k}" r="4.5" fill="${color}" visibility="hidden"/>`).join("")}
      <rect x="${L}" y="${T}" width="${iw}" height="${ih}" fill="transparent" class="hit"/></svg>`;
    const svg = $("svg", el), xh = $(".xh", svg);
    const show = i => {
      i = Math.max(0, Math.min(n - 1, i)); el.dataset.at = i;
      xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
      $$(".hov", svg).forEach(c => { const v = tr[c.dataset.k][i]; c.setAttribute("visibility", v == null ? "hidden" : "visible"); if (v != null) { c.setAttribute("cx", x(i)); c.setAttribute("cy", y(v)); } });
      tip.innerHTML = `<b>${day(tr.dates[i])}</b>` + has.map(([k, name]) => `<br>${name}: ${tr[k][i] == null ? "not reported yet" : plural(tr[k][i], "click")}`).join("");
      tip.hidden = false;
      const r = el.getBoundingClientRect(), tw = tip.getBoundingClientRect().width;
      tip.style.left = Math.min(innerWidth - tw - 8, Math.max(8, r.left + x(i) + 12)) + "px";
      tip.style.top = Math.max(8, r.top + T) + "px";
    };
    const hide = () => { xh.setAttribute("visibility", "hidden"); $$(".hov", svg).forEach(c => c.setAttribute("visibility", "hidden")); tip.hidden = true; };
    const hit = $(".hit", svg);
    hit.addEventListener("mousemove", e => { const r = svg.getBoundingClientRect(); show(Math.round((e.clientX - r.left - L) / iw * (n - 1))); });
    hit.addEventListener("mouseleave", hide);
    const at = () => (el.dataset.at == null ? n - 1 : +el.dataset.at);
    el.onkeydown = e => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); show(at() + (e.key === "ArrowRight" ? 1 : -1)); } };
    el.onfocus = () => show(at());
    el.onblur = hide;
  });
}
let resizeT;
addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(drawCharts, 150); });

/* ---------- Overview ---------- */
const g28 = s => s.google_clicks_28 ?? null, b28 = s => s.bing_clicks_28 ?? null;
function searchLine() {
  const S = D.sites, g = sum(S, g28), b = sum(S, b28);
  if (!S.some(s => s.has_gsc || s.has_bing)) return "";
  const lead = b > g ? `Bing sent <b>${num(b)}</b> clicks and Google <b>${num(g)}</b>` : `Google sent <b>${num(g)}</b> clicks and Bing <b>${num(b)}</b>`;
  return `<li>${icon("dot")}<span>${lead} in the last 4 weeks across all sites.</span></li>`;
}
function indexLine() {
  const S = D.sites, ins = sum(S, s => s.google_inspected), idx = sum(S, s => s.google_indexed);
  return ins ? `<li>${icon("dot")}<span>Google has indexed <b>${num(idx)} of ${num(ins)}</b> pages it was asked about. <a href="#/pages?gidx=not">See the rest</a></span></li>` : "";
}
function briefing() {
  const S = D.sites, withGa = S.filter(s => s.has_ga), clicks = sum(withGa, s => s.ga_clicks);
  const top = [...withGa].sort((a, b) => b.ga_clicks - a.ga_clicks)[0];
  const toFix = sum(S, s => s.to_fix), linked = sum(S, s => s.with_links), late = sum(S, s => s.late);
  const line = clicks && top
    ? (top.ga_clicks === clicks ? `${top.name} produced all ${num(clicks)} recorded Amazon clicks.` : `${top.name} produced ${num(top.ga_clicks)} of ${num(clicks)} recorded Amazon clicks.`)
    : `${plural(toFix, "page")} ${toFix === 1 ? "has" : "have"} a finding that costs clicks or commission.`;
  const crit = D.attention.filter(a => a.severity === "critical").length;
  const first = QUEUE.find(p => !handled(p));
  const li = html => `<li>${icon("dot")}<span>${html}</span></li>`;
  const points = [
    crit ? li(`<b>${plural(crit, "critical finding")}</b> ${crit === 1 ? "needs" : "need"} a decision. <a href="#/findings">Review findings</a>`) : li(`<b>No critical findings</b> in this report.`),
    searchLine(),
    indexLine(),
    linked ? li(`<b>${pct(late / linked)}</b> of pages with Amazon links (${num(late)} of ${num(linked)}) show the first link late in the article.`) : "",
    first ? li(`Top of the work queue: <a href="#" data-open="${esc(first.url)}">${esc(first.path)}</a> on ${esc(first.s.name)}.`) : li(`<b>The work queue is clear.</b>`),
    D.history.length > 1 ? li(`Since ${day(D.previous, 1)}: <b>${signed(D.history.at(-1).links - D.history.at(-2).links)}</b> Amazon links, <b>${signed(D.history.at(-1).pages - D.history.at(-2).pages)}</b> pages audited.`) : "",
  ].join("");
  const next = nextRun();
  const auto = D.auto_fix.length ? D.auto_fix.map(f => `<span class="chip auto" ${tipAttr(esc(FIX_LABEL[f] || f))}>${icon("bolt")}${esc(f)}</span>`).join("") : `<span class="muted">None switched on</span>`;
  return `<section class="card hero">
    <div class="main"><div class="eyebrow">Briefing · ${day(D.generated)}</div><p class="line">${esc(line)}</p><ul>${points}</ul></div>
    <div class="eng"><div class="eyebrow">Engine</div>
      <dl><div><dt>Last run</dt><dd data-run-latest></dd></div>
        ${next ? `<div><dt>Next scheduled run</dt><dd>${esc(when(next))}<span class="muted small">your time</span></dd></div>` : ""}
        <div><dt>Fixes it applies on its own</dt><dd>${auto}</dd></div></dl>
      <div class="acts">${gh("") ? ext(gh("/actions/workflows/weekly-audit.yml"), "Run the engine", "btn primary") : ""}<a class="btn" href="#/controls">Controls</a></div>
    </div></section>`;
}
function sinceLast() {
  if (!D.previous) return `<p class="muted">This is the first report, so there is nothing to compare with yet.</p>`;
  const moved = Object.keys(D.issues).map(c => ({ c, t: trend(c) })).filter(x => x.t && x.t.now !== x.t.was);
  const rows = moved.filter(x => issue(x.c).to_fix)
    .sort((a, b) => RANK[issue(a.c).severity] - RANK[issue(b.c).severity] || Math.abs(b.t.now - b.t.was) - Math.abs(a.t.now - a.t.was));
  const added = sum(D.sites, s => s.new_pages), gone = sum(D.sites, s => s.gone_pages);
  return `<div class="kv" style="margin-bottom:12px"><span><b>${num(added)}</b> new pages</span><span><b>${num(gone)}</b> pages no longer listed</span></div>` +
    (rows.length ? `<div class="scroll"><table><thead><tr><th>Finding</th><th class="n">Before</th><th class="n">Now</th><th class="n">Change</th></tr></thead><tbody>${rows.map(({ c, t }) =>
      `<tr class="row" data-href="#/pages?issue=${c}" tabindex="0"><td>${status(issue(c).severity)}<span class="sub" style="color:var(--ink)" ${tipAttr(esc(issue(c).label))}>${esc(issue(c).short || issue(c).label)}</span></td><td class="n">${num(t.was)}</td><td class="n">${num(t.now)}</td><td class="n"><b>${signed(t.now - t.was)}</b></td></tr>`).join("")}</tbody></table></div>
      <p class="small muted" style="margin-top:10px">A count also moves when a check is refined, not only when pages change.${moved.length > rows.length ? ` ${plural(moved.length - rows.length, "note-level count")} also changed: <a href="#/findings">all findings</a>.` : ""}</p>` : `<p class="muted">No count changed for findings that cost clicks or commission. <a href="#/findings">All findings</a></p>`);
}
function searchTile(label, S, key, clicks, impr) {
  const have = S.filter(s => clicks(s) != null);
  if (!have.length) return tile(label, "–", "No data yet");
  const tr = S.length > 1 ? D.trend : S[0].trend;
  const pts = tr && tr.dates ? weekly(tr, key).slice(-12).map(w => ({ d: w.d, v: w.v })) : [];
  const meta = key === "google" ? have[0].gsc_window : have[0].bing_window;
  return tile(`${label} · 4 weeks`, num(sum(have, clicks)), `${num(sum(have, impr))} impressions${meta?.start ? ` · ${day(meta.start, 1)} to ${day(meta.end, 1)}` : ""}`, spark(pts, `${label} per week`, "weeks"));
}
function indexTile(S) {
  const ins = sum(S, s => s.google_inspected), idx = sum(S, s => s.google_indexed);
  if (!ins) return tile("In Google's index", "–", "Not inspected yet");
  return tile("In Google's index", `${num(idx)}<span class="of"> of ${num(ins)}</span>`, `${pct(idx / ins)} of pages inspected`);
}
function indexHealth(s) {
  if (!s.google_inspected) return "";
  const share = s.google_indexed / s.google_inspected;
  return status(share < 0.25 ? "critical" : share < 0.75 ? "warning" : "good", `Google: ${num(s.google_indexed)} of ${num(s.google_inspected)} indexed`);
}
function overview() {
  const S = D.sites, withGa = S.filter(s => s.has_ga), noGa = S.filter(s => !s.has_ga);
  const attn = D.attention.length
    ? `<ul class="attn">${D.attention.map(a => `<li>${status(a.severity)}<b>${esc(a.title)}</b><span class="detail">${esc(a.detail)}</span>${a.issue ? `<a class="btn go" href="#/pages?issue=${a.issue}">Show pages</a>` : ""}</li>`).join("")}</ul>`
    : `<p>${status("good", "Nothing needs a decision right now.")}</p>`;
  const earners = P.filter(p => p.aclicks > 0).sort((a, b) => b.aclicks - a.aclicks).slice(0, 8);
  const earning = earners.length
    ? bars(earners.map(p => ({ name: p.path, value: p.aclicks, open: p.url, tip: p.s.name })), "recorded Amazon clicks") +
      (noGa.length ? `<p class="small muted" style="margin-top:14px">No Analytics data for ${esc(noGa.map(s => s.name).join(", "))}.</p>` : "")
    : `<p class="muted">No Analytics data yet. The weekly run pulls it once the service account can read the Analytics properties (see <a href="#/controls">Controls</a>).</p>`;
  const fix = bars(S.map(s => ({ name: s.name, value: s.to_fix, href: `#/site/${s.domain}`, tip: `of ${num(s.pages)} pages audited` })).sort((a, b) => b.value - a.value), "pages with a finding that costs clicks or commission");
  const cards = S.map(s => `<a class="card site" href="#/site/${esc(s.domain)}">
      <div class="top"><h3>${esc(s.name)}</h3><span class="dom">${esc(s.domain)}</span></div>
      <dl><div><dt>Google clicks</dt><dd>${num(g28(s))}</dd></div><div><dt>Bing clicks</dt><dd>${num(b28(s))}</dd></div><div><dt>Amazon clicks</dt><dd>${s.has_ga ? num(s.ga_clicks) : "–"}</dd></div></dl>
      ${split(s)}
      <p class="small muted" style="margin-top:8px">${num(s.early)} near top · ${num(s.late)} late · ${num(s.ok - s.with_links)} none</p>
      <div class="chips">${siteHealth(s)}${indexHealth(s)}${s.ga_health ? status("warning", s.ga_health.title) : ""}${s.has_gsc ? "" : status("info", "No Search Console data")}</div>
    </a>`).join("");
  return head("Overview", `${plural(S.length, "site")} · ${plural(P.length, "page")} audited${D.previous ? ` · compared with ${day(D.previous)}` : ""}`,
      `<a class="btn" href="downloads/pages.csv" download>${icon("down")}Download CSV</a>`) +
    `<div class="stack">
      ${briefing()}
      <div class="tiles n6">
        ${searchTile("Google clicks", S, "google", g28, s => s.google_impr_28)}
        ${searchTile("Bing clicks", S, "bing", b28, s => s.bing_impr_28)}
        ${tile("Amazon clicks", withGa.length ? num(sum(withGa, s => s.ga_clicks)) : "–", withGa.length ? `Recorded by Analytics on ${plural(withGa.filter(s => s.ga_clicks).length, "site")}` : "No Analytics data yet")}
        ${indexTile(S)}
        ${trendTile("Pages to fix", D.history, "to_fix")}
        ${trendTile("Pages with Amazon links", D.history, "with_links")}
      </div>
      ${trendCard("all", D.trend, "Search clicks per day", "All sites · Google and Bing")}
      <div class="grid cols-wide">
        ${card("Needs attention", attn, "Worst first")}
        ${card("Since the last report", sinceLast(), D.previous ? `${day(D.previous, 1)} to ${day(D.generated, 1)}` : "")}
      </div>
      <div class="grid cols-2">
        ${card("Pages sending the most people to Amazon", earning, "Select a page for its detail")}
        ${card("Pages to fix by site", fix, "Findings that cost clicks or commission")}
      </div>
      <section><div class="head" style="margin:8px 0 12px"><h2>Sites</h2><div class="right">${LEGEND}</div></div><div class="sites">${cards}</div></section>
    </div>`;
}

/* ---------- Site ---------- */
function site(route) {
  const s = D.sites.find(x => x.domain === route.arg);
  if (!s) return head("Site not found", `No site called ${esc(route.arg)} is in the report.`);
  const i = D.sites.indexOf(s), own = P.filter(p => p.site === i);
  const codes = Object.entries(s.issues).sort((a, b) => RANK[issue(a[0]).severity] - RANK[issue(b[0]).severity] || b[1] - a[1]);
  const findingsHtml = codes.length ? `<div class="meters">${codes.map(([c, n]) => {
      const was = s.prev ? s.prev.issues[c] || 0 : null, d = was == null ? 0 : n - was;
      return `<a class="meter" href="#/pages?site=${esc(s.domain)}&issue=${c}">
      <span>${status(issue(c).severity)}<span class="lbl">${esc(issue(c).label)}</span></span><span class="num">${plural(n, "page")}${d ? ` (${signed(d)})` : ""}</span>
      <span class="bar"><i style="width:${Math.max(1, n / Math.max(1, s.pages) * 100).toFixed(1)}%"></i></span></a>`; }).join("")}</div>` : `<p>${status("good", "No findings on this site.")}</p>`;
  const expected = new Set(s.expected_tags), tags = Object.entries(s.tags_seen).sort((a, b) => b[1] - a[1]);
  const tagBody = (tags.length ? bars(tags.map(([t, n]) => ({ name: t, value: n, note: !expected.size ? "" : expected.has(t) ? "this site's ID" : "not this site's ID" })), "pages") : `<p class="muted">No tracking IDs found on this site's pages.</p>`) +
    `<p class="small muted" style="margin-top:14px">${s.expected_tags.length ? `Expected: ${s.expected_tags.map(t => `<code>${esc(t)}</code>`).join(" ")}` : "No tracking ID is configured for this site in <code>sites.yaml</code>."}</p>`;
  const top = own.filter(p => p.score > 0).sort((a, b) => b.score - a.score).slice(0, 8);
  const topBody = top.length ? table(top, QUEUE_COLS.filter(c => c.key !== "site" && c.key !== "done"), {}) : `<p class="muted">No page on this site has measured demand and a gap to close. Add Search Console or analytics data to rank its pages.</p>`;
  const gw = s.gsc_window, bw = s.bing_window;
  const search = `<ul class="steps" style="padding-left:18px">
      <li><b>Google</b> ${s.has_gsc ? `${plural(g28(s) ?? 0, "click")}, ${plural(s.google_impr_28 ?? 0, "impression")}, ${day(gw?.start, 1)} to ${day(gw?.end)}. ${plural(s.gsc_pages, "page")} had impressions. Property <code>${esc(gw?.property || s.gsc_property)}</code>.` : "No Search Console data for this site yet."}${sitemapLine(s)}</li>
      <li><b>Bing</b> ${s.has_bing ? `${plural(b28(s) ?? 0, "click")}, ${plural(s.bing_impr_28 ?? 0, "impression")}, ${day(bw.start, 1)} to ${day(bw.end)}. Bing names the page for ${bw.page_share_of_clicks == null ? "–" : pct(Math.min(1, bw.page_share_of_clicks))} of those clicks; ${plural(s.bing_pages, "page")} listed.${s.bing_crawl_errors ? ` ${plural(s.bing_crawl_errors, "URL")} with crawl errors.` : ""}` : "No Bing Webmaster data for this site yet."}</li>
      <li><b>IndexNow</b> ${num(s.submitted)} pages submitted, last on ${day(s.last_submission)}${s.submission_status ? ` (${esc(s.submission_status)})` : ""}.</li>
    </ul>`;
  const cov = Object.entries(s.coverage || {}).sort((a, b) => b[1] - a[1]);
  const indexBody = cov.length
    ? bars(cov.map(([c, n]) => ({ name: coverageShort(c), value: n, href: `#/pages?site=${encodeURIComponent(s.domain)}&gidx=${encodeURIComponent(c)}`, tip: D.coverage_advice[c] || c })), "pages") +
      `<p class="small muted" style="margin-top:14px">Google's own verdict for ${plural(s.google_inspected, "page")} (URL Inspection), checked ${day(s.inspected_at)}. Select a state for its pages; hover for what it means.</p>`
    : `<p class="muted">No page on this site has been inspected yet. The next run checks every page with Google's URL Inspection.</p>`;
  const ga = s.ga;
  const gaBody = !ga ? `<p class="muted">No Analytics property is configured for this site (<code>ga4_properties</code> in sites.yaml).</p>` :
    (s.ga_health ? `<p style="margin-bottom:12px">${status("warning", s.ga_health.title)} <span class="muted small">${esc(s.ga_health.detail)}</span></p>` : "") +
    `<div class="kv" style="margin-bottom:12px"><span>Property <b>${esc(ga.property || "none")}</b></span><span><b>${num(ga.sessions)}</b> sessions</span><span><b>${num(ga.organic_sessions)}</b> organic</span><span><b>${num(ga.amazon_clicks)}</b> Amazon clicks</span><span>${day(ga.start, 1)} to ${day(ga.end)}</span></div>` +
    (s.ga_sources.length ? `<div class="scroll"><table><thead><tr><th>Source / medium</th><th class="n">Sessions</th><th class="n">Engaged</th></tr></thead><tbody>${s.ga_sources.slice(0, 8).map(r => `<tr><td>${esc(r.source)} / ${esc(r.medium)}</td><td class="n">${num(+r.sessions)}</td><td class="n">${pct(+r.sessions ? +r.engaged_sessions / +r.sessions : null)}</td></tr>`).join("")}</tbody></table></div>` : "");
  const fixes = D.fixes.filter(f => f.site === s.domain);
  const moved = s.new_pages == null ? "" : ` · ${num(s.new_pages)} new since ${day(D.previous, 1)}`;
  return head(s.name, `${esc(s.domain)} · ${plural(s.pages, "page")} audited${moved}${s.wordpress ? "" : " · not WordPress, so the engine cannot edit it"}`,
      ext("https://" + s.domain + "/", "Open site") + `<a class="btn" href="#/pages?site=${esc(s.domain)}">All pages</a>`, `<a href="#/overview">Overview</a> / Sites`) +
    `<div class="stack">
      <div class="tiles n6">
        ${searchTile("Google clicks", [s], "google", g28, x => x.google_impr_28)}
        ${searchTile("Bing clicks", [s], "bing", b28, x => x.bing_impr_28)}
        ${indexTile([s])}
        ${tile("Amazon clicks", s.has_ga ? num(s.ga_clicks) : "–", s.has_ga ? "Recorded by Analytics" : "No Analytics data")}
        ${trendTile("Pages with Amazon links", s.history, "with_links", s.history.length < 2 ? `${pct(s.with_links / Math.max(1, s.ok))} of pages` : "")}
        ${trendTile("Pages to fix", s.history, "to_fix")}
      </div>
      ${trendCard("site:" + s.domain, s.trend, "Search clicks per day", `${esc(s.domain)} · Google and Bing`)}
      <div class="grid cols-2">
        ${card("Google index status", indexBody, "URL Inspection")}
        ${card("Analytics", gaBody, "Google Analytics 4")}
      </div>
      ${card("Where the first Amazon link sits", split(s) + `<p class="small muted" style="margin:10px 0 12px">${num(s.early)} near top · ${num(s.late)} late · ${num(s.ok - s.with_links)} without Amazon links</p>` + LEGEND)}
      <div class="grid cols-2">
        ${card("Findings", findingsHtml, "Select one to see its pages")}
        <div class="stack">${card("Tracking IDs in use", tagBody, "Pages using each ID")}${card("Search engines", search)}</div>
      </div>
      ${card("Pages to work on first", topBody, "Ranked by measured demand times the gap to close")}
      ${fixes.length ? card("Changes the engine made here", fixTable(fixes, false)) : ""}
    </div>`;
}

function sitemapLine(s) {
  const sm = (s.sitemaps || []).filter(m => !/\/feed\/?$/.test(m.path));
  if (!sm.length) return s.has_gsc ? ` ${status("warning", "No sitemap submitted to Google")}` : "";
  const bad = sm.filter(m => +m.errors), newest = sm.map(m => m.last_downloaded).filter(Boolean).sort().pop();
  return `<br><span class="small muted">Sitemaps Google holds: ${sm.map(m => `<code>${esc(m.path.replace(/^https?:\/\/[^/]+/, ""))}</code> (${num(+m.web_urls)} URLs)`).join(", ")}; last read ${day(newest)}${bad.length ? `; ${plural(bad.length, "sitemap")} with errors` : ", no errors"}.</span>`;
}

/* ---------- tables ---------- */
const pageCell = p => `<span class="path">${esc(p.path)}</span>`;
const withSite = p => `<span class="path">${esc(p.path)}</span><span class="sub">${esc(p.s.name)}</span>`;
const worstChip = p => (p.codes.length ? status(SEVS[p.sev], p.codes.length === 1 ? issue(p.codes[0]).label : `${p.codes.length} findings`) : status("good", "Clean"));
const PAGE_COLS = [
  { key: "url", label: "Page", cls: "page", cell: withSite, sort: p => p.url },
  { key: "sev", label: "Findings", cls: "fit", cell: worstChip, sort: p => p.sev * 100 - p.codes.length },
  { key: "gidx", label: "Google index", cls: "fit", cell: indexChip, sort: p => (p.gidx ? (p.indexed ? 2 : 0) : 1) },
  { key: "links", label: "Links", n: 1, cell: p => num(p.links), sort: p => p.links },
  { key: "depth", label: "First link", n: 1, cell: p => pct(p.depth), sort: p => p.depth ?? 9 },
  { key: "aclicks", label: "Amazon clicks", n: 1, cell: p => num(p.aclicks), sort: p => p.aclicks ?? -1 },
  { key: "sessions", label: "Sessions", n: 1, cell: p => num(p.sessions), sort: p => p.sessions ?? -1 },
  { key: "gclicks", label: "Google clicks", n: 1, cell: p => num(p.gclicks), sort: p => p.gclicks ?? -1 },
  { key: "bclicks", label: "Bing clicks", n: 1, cell: p => num(p.bclicks), sort: p => p.bclicks ?? -1 },
  { key: "score", label: "Priority", n: 1, cell: p => (p.score ? p.score.toFixed(1) : "–"), sort: p => p.score },
];
const nextStep = p => {
  const done = FIXED.get(p.url);
  if (done) return done.status === "fixed" ? status("good", "Fixed by the engine") : status("warning", "Saved, not visible on the live page");
  const gap = ["no_amazon_links", "first_link_very_late", "first_link_late"].find(c => p.codes.includes(c));
  if (!gap && p.codes.includes("demand_page_not_in_google")) return esc(issue("demand_page_not_in_google").action);
  if (!gap) return `<span class="muted">First Amazon link is already near the top. Nothing to change.</span>`;
  const ready = D.boxes[p.url] ? "A hand-written box is ready for this page." : D.drafts[p.url] ? "The engine has drafted a box for this page." : "";
  return esc(issue(gap).action) + (ready ? `<span class="sub">${ready}</span>` : "");
};
const QUEUE_COLS = [
  { key: "done", label: "Done", cls: "chk", cell: p => (FIXED.get(p.url)?.status === "fixed" ? `<input type="checkbox" checked disabled aria-label="Fixed by the engine">` : `<input type="checkbox" data-done="${esc(p.url)}"${DONE[p.url] ? " checked" : ""} aria-label="Mark ${esc(p.path)} as done">`) },
  { key: "url", label: "Page", cls: "page", cell: pageCell },
  { key: "site", label: "Site", cls: "fit", cell: p => esc(p.s.name) },
  { key: "search", label: "Search clicks", n: 1, cell: p => num(p.search || null) },
  { key: "aclicks", label: "Amazon clicks", n: 1, cell: p => num(p.aclicks) },
  { key: "score", label: "Priority", n: 1, cell: p => p.score.toFixed(1) },
  { key: "do", label: "What to do", cls: "do", cell: nextStep },
];
/* rows: page objects. opt: {sort, dir, sortable}. Selecting a row opens the page's detail panel. */
function table(rows, cols, opt) {
  const th = c => {
    const active = opt.sort === c.key;
    const inner = opt.sortable && c.sort ? `<button type="button" data-sort="${c.key}">${esc(c.label)}${active ? (opt.dir === "asc" ? " ▲" : " ▼") : ""}</button>` : esc(c.label);
    return `<th class="${c.n ? "n" : c.cls || ""}"${active ? ` aria-sort="${opt.dir === "asc" ? "ascending" : "descending"}"` : ""}>${inner}</th>`;
  };
  const body = rows.map(p => `<tr class="row${handled(p) && cols[0].key === "done" ? " done" : ""}" data-open="${esc(p.url)}" tabindex="0">${cols.map(c => `<td class="${c.n ? "n" : c.cls || ""}">${c.cell(p)}</td>`).join("")}</tr>`).join("");
  return `<div class="scroll"><table><thead><tr>${cols.map(th).join("")}</tr></thead><tbody>${body || `<tr><td colspan="${cols.length}" class="muted">No pages match.</td></tr>`}</tbody></table></div>`;
}

/* ---------- page detail panel ---------- */
function indexDetail(p) {
  if (!p.gidx) return `<p class="muted small">Not inspected yet. The next run asks Google about every indexable page.</p>`;
  if (p.gverdict === "ERROR") return `<p class="muted small">Google's inspection failed for this page (${esc(p.gidx)}). It is retried on the next run.</p>`;
  const advice = p.codes.includes("google_verdict_outdated")
    ? `Out of date: that was the page when Google last crawled it${p.gcrawl ? ` (${day(p.gcrawl)})` : ""}. It loads and is indexable now, so request indexing in Search Console.`
    : D.coverage_advice[p.gidx] || "";
  return `<p>${indexChip(p)} <span class="muted small">${esc(p.gidx)}${p.gcrawl ? ` · last crawled ${day(p.gcrawl)}` : " · no crawl recorded"}</span></p>${advice ? `<p class="muted small" style="margin-top:6px">${esc(advice)}</p>` : ""}`;
}
let lastFocus = null;
function openPage(url) {
  const p = BY.get(url);
  if (!p) return;
  closePalette();
  lastFocus = document.activeElement;
  const s = p.s, done = FIXED.get(p.url);
  const findings = p.codes.length
    ? `<ul class="find">${p.codes.map(c => `<li><div class="t">${status(issue(c).severity)}<b>${esc(issue(c).label)}</b>${handleChip(handling(c, s))}</div>${issue(c).action ? `<p>${esc(issue(c).action)}</p>` : ""}</li>`).join("")}</ul>`
    : `<p>${status("good", "No findings on this page.")}</p>`;
  const stat = (l, v) => `<div><dt>${l}</dt><dd>${v}</dd></div>`;
  const newBox = gh(`/new/main?filename=boxes/${s.domain}/${slugOf(p)}.html`);
  const box = !D.repository ? "" : D.boxes[p.url]
    ? `<p class="muted small" style="margin-bottom:10px">A hand-written box exists for this page. The engine uses it instead of a generated one.</p><p style="display:flex;gap:8px;flex-wrap:wrap">${ext(gh("/blob/main/" + D.boxes[p.url]), "View box")}${ext(gh("/edit/main/" + D.boxes[p.url]), "Edit box")}</p>`
    : D.drafts[p.url]
    ? `<p class="muted small" style="margin-bottom:10px">The engine drafted a box for this page from the products it already links to. Review it, then save your own version to make it permanent.</p><p style="display:flex;gap:8px;flex-wrap:wrap">${ext(gh("/blob/main/" + D.drafts[p.url]), "View draft")}${ext(newBox, "Write your own")}</p>`
    : s.wordpress ? `<p class="muted small" style="margin-bottom:10px">No box has been written or drafted for this page.</p><p>${ext(newBox, "Write a box")}</p>` : `<p class="muted small">This site is not WordPress, so the engine cannot add a box here.</p>`;
  const inspect = s.gsc_property ? ext(`https://search.google.com/search-console/inspect?resource_id=${encodeURIComponent(s.gsc_property)}&id=${encodeURIComponent(p.url)}`, "Inspect in Search Console") : "";
  drawer.innerHTML = `<div class="dr-head"><div><div class="eyebrow">${esc(s.name)}</div><h2>${esc(p.path)}</h2></div>
      <button class="x" type="button" data-close aria-label="Close">${icon("close")}</button>
      <div class="row">${ext(p.url, "Open page", "btn primary")}${inspect}<button class="btn" type="button" data-copy="${esc(p.url)}">${icon("copy")}Copy URL</button></div></div>
    <div class="dr-body">
      ${done ? `<p>${status(done.status === "fixed" ? "good" : "warning", done.status === "fixed" ? "The engine changed this page" : "The engine saved a change that does not show on the live page")} <span class="muted">${esc(done.changes.replace(/_/g, " ").replace(/=/g, ": "))}</span></p>` : ""}
      <dl class="stats">${stat("Amazon clicks", num(p.aclicks))}${stat("Organic sessions", num(p.sessions))}${stat("Priority", p.score ? p.score.toFixed(1) : "–")}
        ${stat("Google clicks", num(p.gclicks))}${stat("Google impressions", num(p.gimpr))}${stat("Google position", p.gpos ?? "–")}
        ${stat("Bing clicks", num(p.bclicks))}${stat("Bing impressions", num(p.bimpr))}${stat("Bing position", p.bpos ?? "–")}
        ${stat("Amazon links", num(p.links))}${stat("First link at", pct(p.depth))}${stat("Words", num(p.words))}</dl>
      <section><h3>Google index</h3>${indexDetail(p)}</section>
      <section><h3>Findings</h3>${findings}</section>
      <section><h3>Search queries</h3><div id="dr-queries"><p class="muted small">Loading…</p></div></section>
      ${box ? `<section><h3>Product box</h3>${box}</section>` : ""}
      <section><h3>Amazon links on this page</h3><div id="dr-links"><p class="muted small">${p.links ? "Loading…" : "This page has no Amazon links in its article."}</p></div></section>
    </div>`;
  scrim.hidden = drawer.hidden = false;
  $("[data-close]", drawer).focus();
  (QUERIES ||= fetch("queries.json").then(r => (r.ok ? r.json() : {})).catch(() => ({}))).then(all => {
    const box = $("#dr-queries");
    if (!box || !drawer.innerHTML.includes(esc(p.url))) return;
    const q = all[p.url] || {};
    const list = (rows, name) => !rows || !rows.length ? `<p class="muted small">${name}: no queries reported for this page.</p>` :
      `<div class="scroll" style="margin-bottom:10px"><table class="q"><thead><tr><th>${name} query</th><th class="n">Clicks</th><th class="n">Impr.</th><th class="n">Pos.</th></tr></thead><tbody>${
        rows.map(([query, c, i, pos]) => `<tr><td>${esc(query)}</td><td class="n">${num(c)}</td><td class="n">${num(i)}</td><td class="n">${pos ?? "–"}</td></tr>`).join("")}</tbody></table></div>`;
    box.innerHTML = list(q.g, "Google") + list(q.b, "Bing") + `<p class="small muted">Top queries over the last 4 weeks. Both engines withhold rare queries.</p>`;
  });
  if (p.links) (LINKS ||= fetch("links.json").then(r => (r.ok ? r.json() : {})).catch(() => ({}))).then(all => {
    const box = $("#dr-links");
    if (!box || !drawer.innerHTML.includes(esc(p.url))) return;
    const rows = all[p.url] || [], own = new Set(s.expected_tags);
    box.innerHTML = rows.length ? `<ul class="links">${rows.slice(0, 60).map(([href, kind, tag, asin, name]) => {
      let label = name || asin;
      if (!label) { try { label = kind === "search" ? "Search: " + (new URL(href).searchParams.get("k") || "Amazon") : new URL(href).hostname; } catch { label = href; } }
      const tagNote = !tag ? (kind === "short" ? `<span>Short link, tracking ID not visible</span>` : status("critical", "No tracking ID"))
        : own.size && !own.has(tag) ? `${status("warning", "Not this site's ID")}<code>${esc(tag)}</code>` : `<code>${esc(tag)}</code>`;
      return `<li><a href="${esc(href)}" target="_blank" rel="noopener sponsored">${esc(label)}</a><span class="chip">${esc(kind || "link")}</span><span class="sub">${asin && name ? `<span>${esc(asin)}</span>` : ""}${tagNote}</span></li>`;
    }).join("")}</ul>${rows.length > 60 ? `<p class="small muted" style="margin-top:8px">Showing 60 of ${rows.length}. The rest are in <a href="downloads/links.csv" download>links.csv</a>.</p>` : ""}` : `<p class="muted small">No article links were recorded for this page.</p>`;
  });
}
function closeDrawer() {
  if (drawer.hidden) return;
  drawer.hidden = true; scrim.hidden = !palette.hidden ? false : true;
  lastFocus?.focus?.();
}

/* ---------- Pages explorer ---------- */
const PER = 50;
function pages(route) {
  const q = route.q;
  const opts = (list, cur, f) => list.map(x => { const [v, l] = f(x); return `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(l)}</option>`; }).join("");
  const codes = Object.keys(D.issues).filter(total).sort((a, b) => RANK[issue(a).severity] - RANK[issue(b).severity] || issue(a).label.localeCompare(issue(b).label));
  return head("Pages", "Every page the engine audited. Select a row for its findings, links and next step.") +
    `<section class="card"><div class="bd flush">
      <form class="filters" id="filters" onsubmit="return false">
        <input type="search" name="q" placeholder="Search URLs" aria-label="Search URLs" value="${esc(q.q || "")}">
        <select name="site" aria-label="Site"><option value="">All sites</option>${opts(D.sites, q.site || "", s => [s.domain, s.name])}</select>
        <select name="issue" aria-label="Finding"><option value="">Any finding</option>${opts(codes, q.issue || "", c => [c, issue(c).label])}</select>
        <select name="gidx" aria-label="Google index"><option value="">Any index status</option><option value="not"${q.gidx === "not" ? " selected" : ""}>Not in Google's index</option><option value="yes"${q.gidx === "yes" ? " selected" : ""}>In Google's index</option>${opts([...new Set(P.map(p => p.gidx).filter(Boolean))].sort(), q.gidx || "", c => [c, coverageShort(c)])}</select>
        <label class="tog"><input type="checkbox" name="links"${q.links ? " checked" : ""}> Has Amazon links</label>
        <label class="tog"><input type="checkbox" name="visits"${q.visits ? " checked" : ""}> Has measured visitors</label>
      </form>
      <div id="results"></div>
    </div></section>`;
}
pages.after = route => {
  const state = { q: "", site: "", issue: "", gidx: "", links: "", visits: "", sort: "score", dir: "desc", p: "1", ...route.q };
  const idxMatch = p => !state.gidx || (state.gidx === "not" ? p.gidx && p.gverdict !== "ERROR" && !p.indexed : state.gidx === "yes" ? p.indexed : p.gidx === state.gidx);
  const form = $("#filters"), box = $("#results");
  let rows = [];
  const draw = () => {
    const needle = state.q.trim().toLowerCase(), si = state.site ? D.sites.findIndex(s => s.domain === state.site) : -1;
    const scope = P.filter(p => (si < 0 || p.site === si) && (!state.links || p.links > 0) && (!state.visits || p.visits > 0 || p.aclicks > 0) && idxMatch(p) && (!needle || p.url.toLowerCase().includes(needle)));
    rows = scope.filter(p => !state.issue || p.codes.includes(state.issue));
    const col = PAGE_COLS.find(c => c.key === state.sort) || PAGE_COLS[PAGE_COLS.length - 1], sign = state.dir === "asc" ? 1 : -1;
    rows.sort((a, b) => { const x = col.sort(a), y = col.sort(b); return (x < y ? -1 : x > y ? 1 : 0) * sign || b.score - a.score; });
    const last = Math.max(1, Math.ceil(rows.length / PER)), page = Math.min(last, Math.max(1, +state.p || 1));
    const counts = {};
    scope.forEach(p => p.codes.forEach(c => { if (issue(c).to_fix) counts[c] = (counts[c] || 0) + 1; }));
    const chips = Object.keys(counts).sort((a, b) => RANK[issue(a).severity] - RANK[issue(b).severity] || counts[b] - counts[a])
      .map(c => `<button type="button" class="chip" data-issue="${c}" aria-pressed="${state.issue === c}" ${tipAttr(esc(issue(c).label))}>${esc(issue(c).short || issue(c).label)} <b>${num(counts[c])}</b></button>`).join("");
    const hint = state.issue && issue(state.issue).action ? `<p class="small" style="margin:0 0 12px">${status(issue(state.issue).severity)} &nbsp;<span class="muted">${esc(issue(state.issue).action)}</span></p>` : "";
    box.innerHTML = (chips ? `<div class="chips-row" aria-label="Quick filters">${chips}</div>` : "") + hint +
      table(rows.slice((page - 1) * PER, page * PER), PAGE_COLS, { sort: col.key, dir: state.dir, sortable: true }) +
      `<div class="pager"><span><b style="color:var(--ink)">${plural(rows.length, "page")}</b>${rows.length !== P.length ? ` of ${num(P.length)}` : ""}</span>
        <button class="btn sm" type="button" data-export${rows.length ? "" : " disabled"}>${icon("down")}Export these</button><button class="btn sm" type="button" data-urls${rows.length ? "" : " disabled"}>${icon("copy")}Copy URLs</button><span class="grow"></span>
        <button class="btn sm" type="button" data-go="${page - 1}"${page <= 1 ? " disabled" : ""}>Previous</button><span>Page ${page} of ${last}</span><button class="btn sm" type="button" data-go="${page + 1}"${page >= last ? " disabled" : ""}>Next</button></div>`;
    const keep = Object.entries(state).filter(([k, v]) => v && !(k === "sort" && v === "score") && !(k === "dir" && v === "desc") && !(k === "p" && v === "1"));
    history.replaceState(null, "", "#/pages" + (keep.length ? "?" + new URLSearchParams(keep) : ""));
  };
  form.addEventListener("input", () => {
    const f = new FormData(form);
    Object.assign(state, { q: f.get("q") || "", site: f.get("site") || "", issue: f.get("issue") || "", gidx: f.get("gidx") || "", links: f.get("links") ? "1" : "", visits: f.get("visits") ? "1" : "", p: "1" });
    draw();
  });
  box.addEventListener("click", e => {
    const sort = e.target.closest("[data-sort]"), go = e.target.closest("[data-go]"), chip = e.target.closest("[data-issue]");
    if (sort) { const k = sort.dataset.sort; state.dir = state.sort === k && state.dir === "desc" ? "asc" : "desc"; state.sort = k; state.p = "1"; draw(); }
    if (go && !go.disabled) { state.p = go.dataset.go; draw(); box.scrollIntoView({ block: "start" }); }
    if (chip) { state.issue = state.issue === chip.dataset.issue ? "" : chip.dataset.issue; form.elements.issue.value = state.issue; state.p = "1"; draw(); }
    if (e.target.closest("[data-export]")) exportCsv(rows);
    if (e.target.closest("[data-urls]")) copy(rows.map(p => p.url).join("\n"), `${plural(rows.length, "URL")} copied`);
  });
  draw();
};
function exportCsv(rows) {
  const q = v => (/[",\n]/.test(String(v ?? "")) ? `"${String(v).replace(/"/g, '""')}"` : v ?? "");
  const lines = [["site", "url", "findings", "google_index", "google_last_crawl", "amazon_links", "first_link_depth", "tracking_ids", "amazon_clicks", "organic_sessions",
                  "google_clicks", "google_impressions", "google_position", "bing_clicks", "bing_impressions", "bing_position", "priority"]]
    .concat(rows.map(p => [p.s.domain, p.url, p.codes.join(" "), p.gidx, p.gcrawl, p.links, p.depth, p.tags, p.aclicks, p.sessions, p.gclicks, p.gimpr, p.gpos, p.bclicks, p.bimpr, p.bpos, p.score]));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.map(l => l.map(q).join(",")).join("\n") + "\n"], { type: "text/csv" }));
  a.download = `pages-${D.generated}-filtered.csv`;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast(`${plural(rows.length, "page")} exported`);
}

/* ---------- Work queue ---------- */
function queue(route) {
  const show = route.q.show || "open";
  const engine = QUEUE.filter(p => FIXED.get(p.url)?.status === "fixed").length, done = QUEUE.filter(handled).length;
  const rows = QUEUE.filter(p => show === "all" || (show === "done") === handled(p));
  const tab = (k, l, n) => `<a class="btn" href="#/queue${k === "open" ? "" : "?show=" + k}" aria-pressed="${show === k}">${l} <span class="muted">${num(n)}</span></a>`;
  const body = QUEUE.length ? table(rows, QUEUE_COLS, {}) : `<p class="muted">No page has both measured demand and a gap to close. Add Search Console or analytics data (see Controls) so pages can be ranked.</p>`;
  return head("Work queue", "Pages where measured demand meets a gap in Amazon links, highest priority first.", `<div class="seg-ctl" role="group" aria-label="Show">${tab("open", "Open", QUEUE.length - done)}${tab("done", "Done", done)}${tab("all", "All", QUEUE.length)}</div>`) +
    `<div class="stack">
      <section class="card"><div class="bd flush">
        <div style="display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;margin-bottom:10px"><b>${num(done)} of ${num(QUEUE.length)} handled</b><span class="muted small">${num(engine)} fixed by the engine · ${num(done - engine)} ticked by you (kept in this browser only)</span></div>
        <div class="progress" role="img" aria-label="${done} of ${QUEUE.length} pages handled"><i style="width:${(QUEUE.length ? done / QUEUE.length * 100 : 0).toFixed(1)}%"></i></div>
      </div></section>
      <section class="card"><div class="bd flush">${body}
        <p class="small muted" style="margin-top:12px">Priority = clicks the page could reach, times how much of its Amazon potential is unused. Pages without Search Console or analytics data cannot be ranked and are not listed.</p></div></section>
    </div>`;
}

/* ---------- Findings ---------- */
function findings() {
  const section = ([group, title]) => {
    const codes = Object.keys(D.issues).filter(c => issue(c).group === group && total(c)).sort((a, b) => RANK[issue(a).severity] - RANK[issue(b).severity] || total(b) - total(a));
    if (!codes.length) return "";
    const max = Math.max(...codes.map(total));
    return card(title, `<div class="scroll"><table><thead><tr><th class="page">Finding</th><th class="n">Pages</th><th class="n">Change</th><th class="n">Sites</th><th class="fit hb">Handled by</th></tr></thead><tbody>${codes.map(c => {
      const i = issue(c), n = total(c), t = trend(c), d = t ? t.now - t.was : 0, h = handling(c);
      return `<tr class="row" data-href="#/pages?issue=${c}" tabindex="0"><td class="page">${status(i.severity)}<span class="sub" style="color:var(--ink);font-size:13.5px;font-weight:560">${esc(i.label)}</span>${i.action ? `<span class="sub">${esc(i.action)}</span>` : ""}</td>
        <td class="n"><b>${num(n)}</b><span class="inbar"><i style="width:${(n / max * 100).toFixed(1)}%"></i></span></td>
        <td class="n">${t ? (d ? signed(d) : "0") : "–"}</td><td class="n">${D.sites.filter(s => s.issues[c]).length}</td><td class="fit">${h ? handleChip(h) : `<span class="muted">Note only</span>`}</td></tr>`;
    }).join("")}</tbody></table></div>`, group === "money" ? "Select a finding to see its pages" : "");
  };
  const toFix = sum(D.sites, s => s.to_fix), auto = Object.keys(D.issues).filter(c => handling(c)?.cls === "auto" && total(c)).length, off = Object.keys(D.issues).filter(c => issue(c).fix && !issue(c).fix_on && total(c)).length;
  return head("Findings", `Every check the engine runs, across all sites${D.previous ? `, with the change since ${day(D.previous)}` : ""}.`, `<a class="btn" href="#/controls">Change what is automatic</a>`) +
    `<div class="stack">
      <div class="tiles">
        ${tile("Pages to fix", num(toFix), "With a finding that costs clicks or commission")}
        ${tile("Finding types handled automatically", num(auto), "On sites whose login secret exists")}
        ${tile("Automatic fixes switched off", num(off), off ? "Present on pages, fix disabled in sites.yaml" : "")}
      </div>
      ${GROUPS.map(section).join("")}
    </div>`;
}

/* ---------- Activity ---------- */
function fixTable(rows, showSite = true) {
  return `<div class="scroll"><table><thead><tr><th>Page</th><th>Change</th><th>Result</th></tr></thead><tbody>${rows.map(f => {
    let path = f.url; try { path = new URL(f.url).pathname; } catch {}
    const name = D.sites.find(s => s.domain === f.site)?.name || f.site;
    return `<tr class="row" data-open="${esc(f.url)}" tabindex="0"><td><span class="path">${esc(path)}</span>${showSite ? `<span class="sub">${esc(name)}</span>` : ""}</td>
      <td>${esc((f.changes || f.fixes || "").replace(/_/g, " ").replace(/=/g, ": ").replace(/;/g, ", "))}${f.report ? `<span class="sub">${day(f.report)}</span>` : ""}</td>
      <td>${f.status === "fixed" ? status("good", "Live") : status("warning", "Saved, not visible on the live page")}${f.still_failing_on_live_page ? `<span class="sub">Still found: ${esc(f.still_failing_on_live_page.split(" ").map(c => issue(c).label).join(", "))}</span>` : ""}</td></tr>`;
  }).join("")}</tbody></table></div>`;
}
function activity() {
  const subs = D.submissions.length ? `<div class="scroll"><table><thead><tr><th>Site</th><th class="n">New or changed</th><th class="n">Unchanged</th><th class="n">Total submitted</th><th>Result</th></tr></thead><tbody>${D.submissions.map(r => {
    const s = D.sites.find(x => x.domain === r.site), okay = r.status === "submitted" || r.status === "nothing_new";
    return `<tr><td><a href="#/site/${esc(r.site)}">${esc(s?.name || r.site)}</a></td><td class="n">${num(+r.urls_new_or_changed || 0)}</td><td class="n">${num(+r.urls_unchanged || 0)}</td><td class="n">${num(r.total)}</td><td>${status(okay ? "good" : "warning", r.detail || r.status.replace(/_/g, " "))}</td></tr>`;
  }).join("")}</tbody></table></div>` : `<p class="muted">No submission was recorded in this report.</p>`;
  const live = D.fixes.filter(f => f.status === "fixed").length;
  return head("Activity", `What the engine ran, changed and sent. Page changes cover every report; submissions are from the report of ${day(D.generated)}.`) +
    `<div class="stack">
      <div class="tiles">
        ${tile("Page changes live", num(live))}
        ${tile("Saved but not visible", num(D.fixes.length - live), D.fixes.length - live ? "Another plugin rewrites these at display time" : "")}
        ${tile("Pages sent this run", num(sum(D.submissions, r => +r.urls_new_or_changed)), "New or changed since the last submission")}
        ${tile("Pages submitted in total", num(sum(D.sites, s => s.submitted)))}
      </div>
      ${D.repository ? card("Engine runs", `<div data-run-list></div>`, "Live from GitHub", ext(gh("/actions"), "All runs", "btn sm")) : ""}
      ${card("Changes made to pages", D.fixes.length ? fixTable(D.fixes) : `<p class="muted">No page was changed in this report.</p>`, "WordPress keeps the previous version of each page as a revision")}
      ${card("Submissions to search engines", subs, "IndexNow: Bing, Yandex, Seznam, Naver and others. Google does not use it.")}
    </div>`;
}

/* ---------- Notes ---------- */
function notes(route) {
  if (!D.notes.length) return head("Notes", "No notes are in the repository yet.");
  const cur = D.notes.find(n => n.slug === route.arg) || D.notes[0];
  return head("Notes", "The full report and the written findings behind the numbers") +
    `<div class="split"><nav class="card list" aria-label="Notes" style="padding:8px">${D.notes.map(n => `<a href="#/notes/${esc(n.slug)}"${n === cur ? ' aria-current="page"' : ""}>${esc(n.title)}</a>`).join("")}</nav>
      <article class="card"><div class="bd prose flush">${cur.html}</div></article></div>`;
}

/* ---------- Controls ---------- */
function pullStatus() {
  const ps = D.pull_status;
  if (!ps) return "";
  const names = { gsc: "Search Console", inspect: "URL Inspection", bing: "Bing", ga4: "Analytics" };
  return `<p class="kv" style="margin-bottom:12px"><span>Last pull <b>${day(ps.pulled)}</b></span>${Object.entries(ps.sources || {}).map(([k, v]) =>
    `<span ${tipAttr(esc(v))}>${status(v === "ok" ? "good" : v.startsWith("skipped") ? "info" : "warning", `${names[k] || k}: ${v === "ok" ? "ok" : v.startsWith("skipped") ? "skipped" : "problems"}`)}</span>`).join("")}</p>`;
}
function sourcesTable() {
  const cell = (ok, text) => (ok ? `<td>${text}</td>` : `<td class="muted">${text}</td>`);
  return `<div class="scroll"><table><thead><tr><th>Site</th><th>Search Console</th><th>Bing</th><th>Analytics</th><th>Google index check</th></tr></thead><tbody>${D.sites.map(s => {
    const gw = s.gsc_window, bw = s.bing_window, ga = s.ga;
    return `<tr><td><a href="#/site/${esc(s.domain)}">${esc(s.name)}</a></td>
      ${cell(s.has_gsc, s.has_gsc ? `${day(gw.start, 1)} to ${day(gw.end, 1)}<span class="sub">${esc(gw.property || "")}</span>` : "No data")}
      ${cell(s.has_bing, s.has_bing ? `${day(bw.start, 1)} to ${day(bw.end, 1)}<span class="sub">pulled ${day(bw.pulled, 1)}</span>` : "No data")}
      ${cell(ga && ga.sessions, ga ? `${ga.property ? `Property ${esc(ga.property)}` : "No readable property"}<span class="sub">${ga.sessions ? `${day(ga.start, 1)} to ${day(ga.end, 1)}` : esc((ga.notes || [])[0] || "no visits recorded")}</span>` : "Not configured")}
      ${cell(s.google_inspected, s.google_inspected ? `${num(s.google_inspected)} pages<span class="sub">latest ${day(s.inspected_at, 1)}</span>` : "Not yet")}</tr>`;
  }).join("")}</tbody></table></div>`;
}
function controls() {
  const repo = D.repository;
  if (!repo) return head("Controls", "The repository address is not known, so the action links cannot be built. Add <code>repository: owner/name</code> to <code>sites.yaml</code>.");
  const action = (title, text, link) => `<div class="card action"><h3>${esc(title)}</h3><p>${text}</p><div>${link}</div></div>`;
  const cmd = text => `<div class="cmd"><span>${esc(text)}</span><button type="button" data-copy="${esc(text)}">Copy</button></div>`;
  const pick = (id, base, label, tail = "") => `<div class="filters" style="margin:0"><select id="${id}" aria-label="Site">${D.sites.map(s => `<option value="${esc(s.domain)}">${esc(s.name)}</option>`).join("")}</select><a class="btn" data-base="${esc(base)}" data-tail="${esc(tail)}" data-pick="${id}" href="${esc(base + D.sites[0].domain + tail)}" target="_blank" rel="noopener">${esc(label)}${icon("ext")}</a></div>`;
  const auto = Object.keys(FIX_LABEL).map(f => `<li><b>${esc(f)}</b> ${D.auto_fix.includes(f) ? `<span class="chip auto">${icon("bolt")}On</span>` : `<span class="chip">Off</span>`}<br>${esc(FIX_LABEL[f])}</li>`).join("");
  const next = nextRun();
  return head("Controls", `Everything here opens the real control in GitHub, in <a href="${gh("")}" target="_blank" rel="noopener">${esc(repo)}</a>. This dashboard itself changes nothing.`) +
    `<div class="stack">
      ${card("Engine runs", `<div data-run-list></div>${next ? `<p class="small muted" style="margin-top:12px">Next scheduled run: ${esc(when(next))} (your time).</p>` : ""}`, "Live from GitHub",
        ext(gh("/actions/workflows/weekly-audit.yml"), "Run the engine", "btn primary sm") + ext(gh("/actions"), "All runs", "btn sm"))}
      <div class="actions">
        ${action("Run the engine now", "Crawls every site, scores pages, applies the switched-on fixes and submits changed pages. On the page that opens, choose <b>Run workflow</b>. Untick fixes or submissions for a report-only run.", ext(gh("/actions/workflows/weekly-audit.yml"), "Open the workflow", "btn primary"))}
        ${action("Change sites and rules", "Sites, tracking IDs, blocked products and which fixes the engine may apply on its own all live in one file.", ext(gh("/edit/main/sites.yaml"), "Edit sites.yaml"))}
        ${action("Write a product box for a page", "A hand-written box always wins over a generated one. Each page's detail panel has a link with the right file name already filled in.", pick("box-site", gh("/new/main?filename=boxes/"), "New box", "/page-slug.html"))}
        ${action("Give the engine access to a new site", "Add the service account's email as a Full user in Search Console and as a Viewer in Analytics, verify the site in Bing Webmaster Tools, then add the site to sites.yaml. The next run pulls everything.", ext(gh("/edit/main/sites.yaml"), "Edit sites.yaml"))}
        ${action("Add Amazon Associates reports", "Upload the tracking ID summary so earnings can be set beside clicks.", ext(gh("/upload/main/data/associates"), "Upload"))}
        ${action("Logins the engine uses", "Stored as encrypted GitHub secrets, never in the repository. This dashboard cannot see which ones exist.", ext(gh("/settings/secrets/actions"), "Open secrets"))}
        ${action("Past reports", "Every report the engine has written, one folder per run, with the full audit and its fix drafts.", ext(gh("/tree/main/reports"), "Browse reports"))}
      </div>
      <div class="grid cols-2">
        ${card("What the engine fixes on its own", `<ul class="steps">${auto}</ul><p class="small muted" style="margin-top:12px">Set by <code>auto_fix</code> in sites.yaml. Fixes are only applied on sites whose login secret exists.</p>`, "", ext(gh("/edit/main/sites.yaml"), "Change", "btn sm"))}
        ${card("Secrets it looks for", `<ul class="steps">
            <li><b>WP_AUTH_&lt;DOMAIN&gt;</b> one per WordPress site, as <code>username:application password</code>. Without it the site is audited but never edited.</li>
            <li><b>INDEXNOW_KEY</b> lets the weekly run submit new and changed pages to search engines.</li>
            <li><b>GSC_SERVICE_ACCOUNT_JSON</b> the Google service account key. Pulls Search Console (every page and query, the daily trend and Google's index verdict per page) and Google Analytics.</li>
            <li><b>BING_API_KEY</b> the Bing Webmaster Tools API key. Pulls Bing clicks, impressions, queries and crawl errors.</li>
          </ul>`)}
      </div>
      ${card("Data sources", pullStatus() + sourcesTable(), "What each site's numbers are based on")}
      ${card("Downloads from this report", `<p style="display:flex;flex-wrap:wrap;gap:8px">${[["pages.csv", "All pages"], ["links.csv", "All Amazon links"], ["fix-log.csv", "Changes made"], ["indexnow-log.csv", "Submissions"], ["summary.md", "Full report"]].map(([f, l]) => `<a class="btn" href="downloads/${f}" download>${icon("down")}${l}</a>`).join("")}</p>`)}
      ${card("Run it on your own computer", `<div class="stack" style="gap:8px">${cmd("python -m ace run")}${cmd("python -m ace fix")}${cmd("python -m ace fix --apply")}${cmd("python -m ace submit --apply")}${cmd("python -m ace site --site-out dist")}</div>
        <p class="small muted" style="margin-top:12px"><code>fix</code> and <code>submit</code> only show what they would do until <code>--apply</code> is added.</p>`)}
    </div>`;
}
controls.after = () => $$("[data-pick]", view).forEach(a => {
  const sel = $("#" + a.dataset.pick);
  sel.addEventListener("change", () => (a.href = a.dataset.base + sel.value + a.dataset.tail));
});

/* ---------- command palette ---------- */
let palItems = [], palAt = 0;
function palSource(q) {
  const go = (group, label, hint, ic, run) => ({ group, label, hint, ic, run });
  const to = hash => () => (location.hash = hash);
  const out = url => () => window.open(url, "_blank", "noopener");
  const items = [
    ...NAV.map(([k, l]) => go("Go to", l, "", k, to("#/" + k))),
    ...D.sites.map(s => go("Sites", s.name, s.to_fix ? `${num(s.to_fix)} to fix` : s.domain, "site", to("#/site/" + s.domain))),
    ...(D.repository ? [
      go("Actions", "Run the engine", "GitHub", "play", out(gh("/actions/workflows/weekly-audit.yml"))),
      go("Actions", "See past runs", "GitHub", "activity", out(gh("/actions"))),
      go("Actions", "Edit sites and rules (sites.yaml)", "GitHub", "controls", out(gh("/edit/main/sites.yaml"))),
      go("Actions", "Open secrets", "GitHub", "controls", out(gh("/settings/secrets/actions"))),
    ] : []),
    go("Actions", "Switch theme", "", "theme", toggleTheme),
    ...Object.keys(D.issues).filter(total).map(c => go("Findings", issue(c).label, plural(total(c), "page"), "findings", to("#/pages?issue=" + c))),
  ];
  const needle = q.trim().toLowerCase();
  if (!needle) return items.filter(i => i.group !== "Findings");
  const words = needle.split(/\s+/), hit = text => words.every(w => text.includes(w));
  const found = items.filter(i => hit((i.label + " " + i.group).toLowerCase()));
  const pagesFound = P.filter(p => hit(p.url.toLowerCase())).sort((a, b) => (b.aclicks || 0) - (a.aclicks || 0) || b.score - a.score).slice(0, 8)
    .map(p => go("Pages", p.path, p.s.name, "pages", () => openPage(p.url)));
  return [...found.slice(0, 12), ...pagesFound];
}
function palDraw() {
  palItems = palSource($("#pal-q").value);
  palAt = Math.min(palAt, Math.max(0, palItems.length - 1));
  let group = "";
  $("#pal-list").innerHTML = palItems.length ? palItems.map((it, i) => {
    const h = it.group !== group ? `<div class="pal-g">${esc(it.group)}</div>` : "";
    group = it.group;
    return `${h}<div class="pal-i" role="option" data-i="${i}" aria-selected="${i === palAt}">${icon(it.ic)}<span>${esc(it.label)}</span>${it.hint ? `<small>${esc(it.hint)}</small>` : ""}</div>`;
  }).join("") : `<div class="pal-empty">Nothing matches. Try part of a URL, a site name or a finding.</div>`;
  $(`[data-i="${palAt}"]`, palette)?.scrollIntoView({ block: "nearest" });
}
function openPalette() {
  if (!D) return;
  lastFocus = drawer.hidden ? document.activeElement : lastFocus;
  palette.hidden = scrim.hidden = false;
  const q = $("#pal-q"); q.value = ""; palAt = 0; palDraw(); q.focus();
}
function closePalette() {
  if (palette.hidden) return;
  palette.hidden = true; scrim.hidden = drawer.hidden;
}
function palRun(i) { const it = palItems[i]; if (!it) return; closePalette(); it.run(); }
$("#pal-q").addEventListener("input", () => { palAt = 0; palDraw(); });
$("#pal-q").addEventListener("keydown", e => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); palAt = (palAt + (e.key === "ArrowDown" ? 1 : -1) + palItems.length) % Math.max(1, palItems.length); palDraw(); }
  if (e.key === "Enter") { e.preventDefault(); palRun(palAt); }
});
$("#pal-list").addEventListener("click", e => { const it = e.target.closest("[data-i]"); if (it) palRun(+it.dataset.i); });
$("#search-open").addEventListener("click", openPalette);
$("#search-key").textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Ctrl K";

/* ---------- global interactions ---------- */
document.addEventListener("keydown", e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) { e.preventDefault(); palette.hidden ? openPalette() : closePalette(); return; }
  if (e.key === "Escape") { if (!palette.hidden) { closePalette(); if (drawer.hidden) lastFocus?.focus?.(); } else closeDrawer(); return; }
  if ((e.key === "Enter" || e.key === " ") && e.target.matches?.("tr.row")) { e.preventDefault(); e.target.click(); }
});
scrim.addEventListener("click", () => { closePalette(); closeDrawer(); });
document.addEventListener("click", e => {
  const t = e.target;
  if (t.closest("[data-close]")) return closeDrawer();
  const cp = t.closest("[data-copy]");
  if (cp) return copy(cp.dataset.copy);
  const done = t.closest("[data-done]");
  if (done) {
    done.checked ? (DONE[done.dataset.done] = D.generated) : delete DONE[done.dataset.done];
    store.set("ace-queue-done", DONE);
    return render();
  }
  if (t.closest("a,button,input,select,label") && !t.closest("a[data-open]")) return;
  const open = t.closest("[data-open]");
  if (open) { e.preventDefault(); return openPage(open.dataset.open); }
  const row = t.closest("tr[data-href]");
  if (row) location.hash = row.dataset.href;
});

function showTip(el, x, y) {
  tip.innerHTML = el.dataset.tip;
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(x + 12, innerWidth - r.width - 8)) + "px";
  tip.style.top = (y + 16 + r.height > innerHeight ? y - r.height - 10 : y + 16) + "px";
}
document.addEventListener("mousemove", e => {
  if (e.target.closest?.(".chart")) return;  // the chart runs its own tooltip
  const el = e.target.closest?.("[data-tip]");
  el ? showTip(el, e.clientX, e.clientY) : (tip.hidden = true);
});
document.addEventListener("focusin", e => { const el = e.target.closest?.("[data-tip]"); if (el) { const r = el.getBoundingClientRect(); showTip(el, r.left, r.bottom - 8); } });
document.addEventListener("focusout", () => (tip.hidden = true));
document.addEventListener("scroll", () => (tip.hidden = true), { passive: true, capture: true });

function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("ace-theme", root.dataset.theme); } catch {}
}
$("#theme").addEventListener("click", toggleTheme);

/* ---------- start ---------- */
fetch("data.json", { cache: "no-cache" })
  .then(r => { if (!r.ok) throw new Error("data.json: HTTP " + r.status); return r.json(); })
  .then(data => {
    prepare(data);
    $("#brand-date").textContent = "Report of " + day(D.generated);
    if (D.repository) $("#run-btn").innerHTML = ext(gh("/actions/workflows/weekly-audit.yml"), "Run the engine", "btn primary");
    addEventListener("hashchange", () => { closeDrawer(); render(); });
    render();
    loadRuns();
  })
  .catch(err => { view.innerHTML = `<div class="card"><div class="bd flush"><h2>The report could not be loaded</h2><p class="muted" style="margin-top:6px">${esc(err.message)}. Rebuild with <code>python -m ace site</code>.</p></div></div>`; });
})();
