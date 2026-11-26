/* Commission Engine dashboard. One data file (data.json, built by `python -m ace site`), no
   dependencies. Every number on screen comes from that file; every button is a real link. */
(() => {
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const view = $("#view"), tip = $("#tip");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("en-US");
const num = n => (n == null ? "–" : nf.format(n));
const pct = x => (x == null ? "–" : Math.round(x * 100) + "%");
const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : many || one + "s"}`;
const day = iso => {
  const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(iso || "");
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : (iso || "–");
};
const sum = (list, f) => list.reduce((a, x) => a + (f(x) || 0), 0);

const RANK = { critical: 0, serious: 1, warning: 2, info: 3, good: 4 };
const SEV_LABEL = { critical: "Critical", serious: "Serious", warning: "Warning", info: "Note", good: "OK" };
const ICON = {
  critical: '<path d="M8.3 2h7.4L22 8.3v7.4L15.7 22H8.3L2 15.7V8.3z" fill="currentColor"/><path d="M12 7v6m0 3.5v.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>',
  serious: '<path d="M12 2.5 23 21H1z" fill="currentColor"/><path d="M12 9.5v5m0 3v.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>',
  warning: '<circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M12 7v6m0 3.5v.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>',
  good: '<circle cx="12" cy="12" r="10" fill="currentColor"/><path d="m7.5 12.5 3 3 6-6.5" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
  info: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 11v6m0-9.5v.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
};
const NAV_ICON = {
  overview: '<path d="M4 13h6V4H4zm10 7h6v-9h-6zM4 20h6v-4H4zM14 4v4h6V4z"/>',
  queue: '<path d="M4 6h16M4 12h10M4 18h6"/><path d="m16 16 2.5 2.5L22 14"/>',
  pages: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  notes: '<path d="M5 4h14v16H5z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
  controls: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
  site: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  ext: '<path d="M14 5h5v5M19 5l-8 8M11 7H6v11h11v-5"/>',
};
const icon = (name, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${NAV_ICON[name]}</svg>`;
const status = (sev, text) => `<span class="st ${sev}"><svg viewBox="0 0 24 24" aria-hidden="true">${ICON[sev] || ICON.info}</svg>${esc(text ?? SEV_LABEL[sev])}</span>`;
const ext = (href, text, cls = "btn") => `<a class="${cls}" href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}${cls.includes("btn") ? icon("ext") : ""}</a>`;
const tipAttr = html => `data-tip="${esc(html)}" tabindex="0"`;

const FIX_LABEL = {
  rel: "Marks Amazon links as sponsored (rel attribute).",
  blocked: "Repoints links that lead to a product marked wrong or gone.",
  box: "Adds a product box near the top of pages that have visitors and a late first link.",
  tags: "Adds or corrects the tracking ID on Amazon links.",
  disclosure: "Adds an affiliate disclosure where one is missing.",
};

let D, P, QUEUE, FIXED;

/* ---------- data ---------- */
function prepare(data) {
  D = data;
  Object.values(D.issues).forEach(i => (i.label = i.label.charAt(0).toUpperCase() + i.label.slice(1)));
  P = D.pages.map(row => {
    const p = {};
    D.cols.forEach((c, i) => (p[c] = row[i]));
    p.s = D.sites[p.site];
    p.codes = p.issues ? p.issues.split(" ") : [];
    try { const u = new URL(p.url); p.path = u.pathname + u.search; } catch { p.path = p.url; }
    p.sev = Math.min(4, ...p.codes.map(c => RANK[D.issues[c]?.severity] ?? 3));
    p.money = p.codes.some(c => D.issues[c]?.group === "money" && D.issues[c].severity !== "info");
    p.visits = Math.max(p.sessions || 0, p.gclicks || 0);
    return p;
  });
  QUEUE = P.filter(p => p.score > 0).sort((a, b) => b.score - a.score);
  FIXED = new Map(D.fixes.map(f => [f.url, f]));
  D.sites.forEach((s, i) => {
    const own = P.filter(p => p.site === i);
    s.money = own.filter(p => p.money).length;
    s.worst = Math.min(4, ...own.filter(p => p.money).map(p => p.sev));
  });
}
const issue = code => D.issues[code] || { label: code.replace(/_/g, " "), severity: "info", action: "", group: "search" };
const gh = path => (D.repository ? `https://github.com/${D.repository}${path}` : "");

/* ---------- routing ---------- */
function parse() {
  const raw = location.hash.replace(/^#\/?/, "") || "overview";
  const [path, query = ""] = raw.split("?");
  const [name, ...rest] = path.split("/");
  return { name, arg: decodeURIComponent(rest.join("/")), q: Object.fromEntries(new URLSearchParams(query)) };
}
const VIEWS = { overview, site, pages, queue, activity, notes, controls };

function nav(route) {
  const item = (href, key, label, count, current) =>
    `<a href="#/${href}"${current ? ' aria-current="page"' : ""}>${icon(key)}<span>${esc(label)}</span>${count != null ? `<span class="count">${num(count)}</span>` : ""}</a>`;
  $("#nav").innerHTML =
    item("overview", "overview", "Overview", null, route.name === "overview") +
    item("queue", "queue", "Work queue", QUEUE.length, route.name === "queue") +
    item("pages", "pages", "Pages", P.length, route.name === "pages") +
    item("activity", "activity", "Activity", D.fixes.length, route.name === "activity") +
    item("notes", "notes", "Notes", null, route.name === "notes") +
    item("controls", "controls", "Controls", null, route.name === "controls") +
    `<div class="nav-h">Sites</div>` +
    D.sites.map(s => item("site/" + s.domain, "site", s.name, null, route.name === "site" && route.arg === s.domain).replace("<a ", '<a class="nav-site" ')).join("");
}

function render() {
  const route = parse();
  nav(route);
  const fn = VIEWS[route.name] || overview;
  view.innerHTML = fn(route) || "";
  if (fn.after) fn.after(route);
  if (render.last !== route.name + "/" + route.arg) { window.scrollTo(0, 0); render.last = route.name + "/" + route.arg; }
  document.title = ($("h1", view)?.textContent || "Overview") + " · Commission Engine";
}

/* ---------- building blocks ---------- */
const head = (title, sub, right = "", crumb = "") =>
  `<header class="head"><div>${crumb ? `<div class="crumb">${crumb}</div>` : ""}<h1>${esc(title)}</h1>${sub ? `<p class="sub">${sub}</p>` : ""}</div><div class="right">${right}</div></header>`;
const tile = (label, value, note = "") =>
  `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${value}</div>${note ? `<div class="delta">${note}</div>` : ""}</div>`;
const card = (title, body, sub = "") =>
  `<section class="card"><div class="hd"><h2>${esc(title)}</h2>${sub ? `<span class="muted">${sub}</span>` : ""}</div><div class="bd">${body}</div></section>`;

function delta(key) {
  if (!D.previous) return "";
  const both = D.sites.filter(s => s.prev);
  const d = sum(both, s => s[key]) - sum(both, s => s.prev[key]);
  return d === 0 ? `No change since ${day(D.previous)}` : `${d > 0 ? "+" : "−"}${num(Math.abs(d))} since ${day(D.previous)}`;
}

/* Ranked horizontal bars, one hue, value at the tip, hover detail. rows: [{name, value, href, tip}] */
function bars(rows, unit) {
  const max = Math.max(1, ...rows.map(r => r.value));
  return `<div class="bars" role="list">${rows.map(r => {
    const name = (r.href ? `<a href="${esc(r.href)}">${esc(r.name)}</a>` : esc(r.name)) + (r.note ? `<small>${esc(r.note)}</small>` : "");
    return `<div class="name" role="listitem">${name}</div>
      <div class="track${r.value ? "" : " zero"}" ${tipAttr(`<b>${esc(r.name)}</b><br>${num(r.value)} ${esc(unit)}${r.tip ? "<br>" + r.tip : ""}`)}><span class="fill" style="width:${(r.value / max * 100).toFixed(1)}%"></span></div>
      <div class="val">${num(r.value)}</div>`;
  }).join("")}</div>`;
}

function split(s) {
  const none = s.ok - s.with_links, total = Math.max(1, s.ok);
  const w = n => (n / total * 100).toFixed(2) + "%";
  const seg = (cls, n, label) => (n ? `<i class="${cls}" style="width:${w(n)}" ${tipAttr(`<b>${esc(s.name)}</b><br>${plural(n, "page")} ${label}`)}></i>` : "");
  return `<div class="seg" role="img" aria-label="${s.early} pages with an early Amazon link, ${s.late} with a late one, ${none} with none">${seg("a", s.early, "with a link near the top")}${seg("b", s.late, "with a late first link")}${seg("c", none, "without Amazon links")}</div>`;
}
const LEGEND = `<div class="legend"><span><i style="background:var(--data-1)"></i>Amazon link near the top</span><span><i style="background:var(--data-2)"></i>First link late</span><span><i style="background:var(--data-0)"></i>No Amazon links</span></div>`;

const siteHealth = s => (s.money ? status(Object.keys(RANK)[s.worst], `${plural(s.money, "page")} to fix`) : status("good", "No money findings"));

/* ---------- Overview ---------- */
function overview() {
  const S = D.sites, withGa = S.filter(s => s.has_ga), noGa = S.filter(s => !s.has_ga);
  const run = gh("/actions/workflows/weekly-audit.yml");
  const attn = D.attention.length
    ? `<ul class="attn">${D.attention.map(a => `<li>${status(a.severity)}<b>${esc(a.title)}</b><span class="detail">${esc(a.detail)}</span>${a.issue ? `<a class="btn go" href="#/pages?issue=${a.issue}">Show pages</a>` : ""}</li>`).join("")}</ul>`
    : `<p>${status("good", "Nothing needs a decision right now.")}</p>`;
  const clicks = withGa.length
    ? bars(withGa.map(s => ({ name: s.name, value: s.ga_clicks, href: "#/site/" + s.domain })).sort((a, b) => b.value - a.value), "recorded Amazon clicks") +
      (noGa.length ? `<p class="small muted" style="margin-top:14px">No analytics export yet for ${esc(noGa.map(s => s.name).join(", "))}.</p>` : "")
    : `<p class="muted">No analytics export has been added yet. Add one under <code>data/ga4/</code> (see Controls).</p>`;
  const money = bars(S.map(s => ({ name: s.name, value: s.money, href: `#/site/${s.domain}`, tip: `of ${num(s.pages)} pages audited` })).sort((a, b) => b.value - a.value), "pages with a finding that costs clicks or commission");
  const cards = S.map(s => `<a class="card site" href="#/site/${esc(s.domain)}">
      <div class="top"><h3>${esc(s.name)}</h3><span class="dom">${esc(s.domain)}</span></div>
      <dl><div><dt>Pages</dt><dd>${num(s.pages)}</dd></div><div><dt>With links</dt><dd>${num(s.with_links)}</dd></div><div><dt>Amazon clicks</dt><dd>${s.has_ga ? num(s.ga_clicks) : "–"}</dd></div></dl>
      ${split(s)}
      <p class="small muted" style="margin-top:8px">${num(s.early)} near top · ${num(s.late)} late · ${num(s.ok - s.with_links)} none</p>
      <div class="chips">${siteHealth(s)}${s.submitted ? status("good", `${num(s.submitted)} submitted`) : status("warning", "Not submitted")}${s.has_gsc ? "" : status("info", "No Search Console data")}</div>
    </a>`).join("");
  return head("Overview", `Report of ${day(D.generated)} · ${plural(S.length, "site")}${D.previous ? ` · compared with ${day(D.previous)}` : ""}`,
      (run ? ext(run, "Run the engine", "btn primary") : "") + `<a class="btn" href="downloads/pages.csv" download>Download CSV</a>`) +
    `<div class="stack">
      <div class="tiles">
        ${tile("Pages audited", num(P.length), delta("pages"))}
        ${tile("Pages with Amazon links", num(sum(S, s => s.with_links)), delta("with_links"))}
        ${tile("Amazon links", num(sum(S, s => s.links)), delta("links"))}
        ${tile("Recorded Amazon clicks", withGa.length ? num(sum(withGa, s => s.ga_clicks)) : "–", withGa.length ? `From analytics exports for ${plural(withGa.length, "site")}` : "No analytics export yet")}
        ${tile("Pages to fix", num(P.filter(p => p.money).length), "With a finding that costs clicks or commission")}
        ${tile("Submitted to search engines", num(sum(S, s => s.submitted)), `Across ${plural(S.filter(s => s.submitted).length, "site")}`)}
      </div>
      ${card("Needs attention", attn, "Counted from the latest crawl, worst first")}
      <div class="grid cols-2">
        ${card("Recorded Amazon clicks by site", clicks, "From the analytics exports in data/ga4")}
        ${card("Pages to fix by site", money, "Findings that cost clicks or commission")}
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
  const findings = codes.length ? `<div class="meters">${codes.map(([c, n]) => `<a class="meter" href="#/pages?site=${esc(s.domain)}&issue=${c}">
      <span>${status(issue(c).severity)}<span>${esc(issue(c).label)}</span></span><span class="num">${plural(n, "page")}</span>
      <span class="bar"><i style="width:${Math.max(1, n / Math.max(1, s.pages) * 100).toFixed(1)}%"></i></span></a>`).join("")}</div>` : `<p>${status("good", "No findings on this site.")}</p>`;
  const expected = new Set(s.expected_tags);
  const tags = Object.entries(s.tags_seen).sort((a, b) => b[1] - a[1]);
  const tagBody = (tags.length ? bars(tags.map(([t, n]) => ({ name: t, value: n, note: !expected.size ? "" : expected.has(t) ? "this site's ID" : "not this site's ID" })), "pages") : `<p class="muted">No tracking IDs found on this site's pages.</p>`) +
    `<p class="small muted" style="margin-top:14px">${s.expected_tags.length ? `Expected: ${s.expected_tags.map(t => `<code>${esc(t)}</code>`).join(" ")}` : "No tracking ID is configured for this site in <code>sites.yaml</code>."}</p>`;
  const top = own.filter(p => p.score > 0).sort((a, b) => b.score - a.score).slice(0, 8);
  const topBody = top.length ? table(top, QUEUE_COLS.filter(c => c.key !== "site"), {}) : `<p class="muted">No page on this site has measured demand and a gap to close. Add Search Console or analytics data to rank its pages.</p>`;
  const search = `<div class="kv">
      <span><b>${num(s.submitted)}</b> pages submitted</span>
      <span>Last submission <b>${day(s.last_submission)}</b></span>
      ${s.submission_status ? `<span>Result <b>${esc(s.submission_status)}</b></span>` : ""}
      <span>${plural(s.noindex, "page")} set to noindex</span>
    </div>
    <p class="small muted" style="margin-top:12px">${s.has_gsc ? `Search Console data: ${esc(s.gsc_window?.start || "")} to ${esc(s.gsc_window?.end || "")}${s.gsc_window?.note ? ` (${esc(s.gsc_window.note)})` : ""}. ${num(s.gsc_clicks)} clicks, ${num(s.gsc_impressions)} impressions on ${plural(s.gsc_pages, "page")}.` : "No Search Console data for this site yet, so its pages cannot be ranked by Google demand."}</p>`;
  const fixes = D.fixes.filter(f => f.site === s.domain);
  return head(s.name, `${esc(s.domain)} · ${plural(s.pages, "page")} audited${s.wordpress ? "" : " · not WordPress, so the fixer leaves it alone"}`,
      ext("https://" + s.domain + "/", "Open site") + `<a class="btn" href="#/pages?site=${esc(s.domain)}">All pages</a>`,
      `<a href="#/overview">Overview</a> / Sites`) +
    `<div class="stack">
      <div class="tiles">
        ${tile("Pages with Amazon links", num(s.with_links), `${pct(s.with_links / Math.max(1, s.ok))} of pages`)}
        ${tile("Amazon links", num(s.links))}
        ${tile("First link position", s.median_depth == null ? "–" : pct(s.median_depth), "Median distance down the page")}
        ${tile("Recorded Amazon clicks", s.has_ga ? num(s.ga_clicks) : "–", s.has_ga ? "From the analytics export" : "No analytics export yet")}
        ${tile("Google clicks", s.has_gsc ? num(s.gsc_clicks) : "–", s.has_gsc ? `${num(s.gsc_impressions)} impressions` : "No Search Console data")}
        ${tile("Pages to fix", num(s.money))}
      </div>
      ${card("Where the first Amazon link sits", split(s) + `<p class="small muted" style="margin:10px 0 12px">${num(s.early)} near top · ${num(s.late)} late · ${num(s.ok - s.with_links)} without Amazon links</p>` + LEGEND)}
      <div class="grid cols-2">
        ${card("Findings", findings, "Select one to see its pages")}
        <div class="stack">${card("Tracking IDs in use", tagBody, "Pages using each ID")}${card("Search engines", search)}</div>
      </div>
      ${card("Pages to work on first", topBody, "Ranked by measured demand times the gap to close")}
      ${fixes.length ? card("Changes the engine made here", fixTable(fixes, false)) : ""}
    </div>`;
}

/* ---------- tables ---------- */
const pageCell = p => `<span class="path">${esc(p.path)}</span>`;
const withSite = p => `<span class="path">${esc(p.path)}</span><span class="sub">${esc(p.s.name)}</span>`;
const worstChip = p => (p.codes.length ? status(Object.keys(RANK)[p.sev], p.codes.length === 1 ? issue(p.codes[0]).label : `${p.codes.length} findings`) : status("good", "Clean"));
const PAGE_COLS = [
  { key: "url", label: "Page", cls: "page", cell: withSite, sort: p => p.url },
  { key: "sev", label: "Findings", cls: "fit", cell: worstChip, sort: p => p.sev * 100 - p.codes.length },
  { key: "links", label: "Links", n: 1, cell: p => num(p.links), sort: p => p.links },
  { key: "depth", label: "First link", n: 1, cell: p => pct(p.depth), sort: p => p.depth ?? 9 },
  { key: "aclicks", label: "Amazon clicks", n: 1, cell: p => num(p.aclicks), sort: p => p.aclicks ?? -1 },
  { key: "sessions", label: "Sessions", n: 1, cell: p => num(p.sessions), sort: p => p.sessions ?? -1 },
  { key: "gclicks", label: "Google clicks", n: 1, cell: p => num(p.gclicks), sort: p => p.gclicks ?? -1 },
  { key: "gimpr", label: "Impressions", n: 1, cell: p => num(p.gimpr), sort: p => p.gimpr ?? -1 },
  { key: "score", label: "Priority", n: 1, cell: p => (p.score ? p.score.toFixed(1) : "–"), sort: p => p.score },
];
const firstAction = p => {
  const done = FIXED.get(p.url);
  if (done) return done.status === "fixed" ? status("good", "Fixed by the engine") : status("warning", "Saved, not visible on the live page");
  const gap = ["no_amazon_links", "first_link_very_late", "first_link_late"].find(c => p.codes.includes(c));
  return gap ? esc(issue(gap).action) : `<span class="muted">First Amazon link is already near the top. Nothing to change.</span>`;
};
const QUEUE_COLS = [
  { key: "rank", label: "#", n: 1, cell: (p, i) => i + 1 },
  { key: "url", label: "Page", cls: "page", cell: pageCell },
  { key: "site", label: "Site", cls: "fit", cell: p => esc(p.s.name) },
  { key: "gimpr", label: "Impressions", n: 1, cell: p => num(p.gimpr) },
  { key: "aclicks", label: "Amazon clicks", n: 1, cell: p => num(p.aclicks) },
  { key: "score", label: "Priority", n: 1, cell: p => p.score.toFixed(1) },
  { key: "do", label: "What to do", cls: "do", cell: firstAction },
];

function detail(p, span) {
  const findings = p.codes.length
    ? `<ul>${[...p.codes].sort((a, b) => RANK[issue(a).severity] - RANK[issue(b).severity]).map(c => `<li>${status(issue(c).severity)} &nbsp;<b>${esc(issue(c).label)}</b>${issue(c).action ? `<br><span class="muted">${esc(issue(c).action)}</span>` : ""}</li>`).join("")}</ul>`
    : `<p>${status("good", "No findings on this page.")}</p>`;
  const done = FIXED.get(p.url);
  const inspect = p.s.gsc_property ? ext(`https://search.google.com/search-console/inspect?resource_id=${encodeURIComponent(p.s.gsc_property)}&id=${encodeURIComponent(p.url)}`, "Inspect in Search Console") : "";
  return `<tr class="detail"><td colspan="${span}">
    <div class="kv"><span>Status <b>${p.status}</b></span><span>Words <b>${num(p.words)}</b></span><span>Product links <b>${num(p.product)}</b></span><span>Search links <b>${num(p.search)}</b></span>
      <span>Tracking IDs <b>${esc(p.tags || "none")}</b></span>${p.gpos != null ? `<span>Google position <b>${p.gpos}</b></span>` : ""}${p.dup != null ? `<span>Near-duplicate group <b>${p.dup}</b></span>` : ""}</div>
    ${done ? `<p style="margin-top:10px">${status(done.status === "fixed" ? "good" : "warning", done.status === "fixed" ? "The engine changed this page" : "The engine saved a change that does not show on the live page")} <span class="muted">${esc(done.changes.replace(/_/g, " ").replace(/=/g, ": "))}</span></p>` : ""}
    ${findings}
    <p style="margin-top:12px;display:flex;flex-wrap:wrap;gap:8px">${ext(p.url, "Open page")}${inspect}</p>
  </td></tr>`;
}

/* rows: page objects. opt: {sort, dir, open(Set of urls), sortable} */
function table(rows, cols, opt) {
  const th = c => {
    const active = opt.sort === c.key;
    const inner = opt.sortable && c.sort ? `<button type="button" data-sort="${c.key}">${esc(c.label)}${active ? (opt.dir === "asc" ? " ▲" : " ▼") : ""}</button>` : esc(c.label);
    return `<th class="${c.n ? "n" : c.cls || ""}"${active ? ` aria-sort="${opt.dir === "asc" ? "ascending" : "descending"}"` : ""}>${inner}</th>`;
  };
  const body = rows.map((p, i) => `<tr class="row" data-url="${esc(p.url)}" tabindex="0" aria-expanded="${opt.open?.has(p.url) ? "true" : "false"}">${cols.map(c => `<td class="${c.n ? "n" : c.cls || ""}">${c.cell(p, i + (opt.offset || 0))}</td>`).join("")}</tr>${opt.open?.has(p.url) ? detail(p, cols.length) : ""}`).join("");
  return `<div class="scroll" data-table><table><thead><tr>${cols.map(th).join("")}</tr></thead><tbody>${body || `<tr><td colspan="${cols.length}" class="muted">No pages match.</td></tr>`}</tbody></table></div>`;
}
const BY_URL = () => (BY_URL.map ||= new Map(P.map(p => [p.url, p])));

/* Any table row opens its detail in place. */
view.addEventListener("click", e => {
  if (e.target.closest("a,button,input,select,label")) return;
  const row = e.target.closest("tr.row");
  if (row) toggleRow(row);
});
view.addEventListener("keydown", e => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr.row")) { e.preventDefault(); toggleRow(e.target); }
});
function toggleRow(row) {
  const next = row.nextElementSibling, open = next?.classList.contains("detail");
  if (open) next.remove();
  else { const p = BY_URL().get(row.dataset.url); if (p) row.insertAdjacentHTML("afterend", detail(p, row.children.length)); }
  row.setAttribute("aria-expanded", open ? "false" : "true");
}

/* ---------- Pages explorer ---------- */
const PER = 50;
function pages(route) {
  const q = route.q;
  const opts = (list, cur, f) => list.map(x => { const [v, l] = f(x); return `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(l)}</option>`; }).join("");
  const codes = Object.keys(D.issues).filter(c => P.some(p => p.codes.includes(c))).sort((a, b) => RANK[issue(a).severity] - RANK[issue(b).severity] || issue(a).label.localeCompare(issue(b).label));
  return head("Pages", "Every page the engine audited. Select a row for its findings and what to do.", `<a class="btn" href="downloads/pages.csv" download>Download CSV</a>`) +
    `<section class="card"><div class="bd" style="padding-top:18px">
      <form class="filters" id="filters" onsubmit="return false">
        <input type="search" name="q" placeholder="Search URLs" aria-label="Search URLs" value="${esc(q.q || "")}">
        <select name="site" aria-label="Site"><option value="">All sites</option>${opts(D.sites, q.site || "", s => [s.domain, s.name])}</select>
        <select name="issue" aria-label="Finding"><option value="">Any finding</option>${opts(codes, q.issue || "", c => [c, issue(c).label])}</select>
        <label class="tog"><input type="checkbox" name="links"${q.links ? " checked" : ""}> Has Amazon links</label>
        <label class="tog"><input type="checkbox" name="visits"${q.visits ? " checked" : ""}> Has measured visitors</label>
      </form>
      <div id="results"></div>
    </div></section>`;
}
pages.after = route => {
  const state = { q: "", site: "", issue: "", links: "", visits: "", sort: "score", dir: "desc", p: "1", ...route.q };
  const form = $("#filters"), box = $("#results");
  const draw = () => {
    const needle = state.q.trim().toLowerCase(), si = state.site ? D.sites.findIndex(s => s.domain === state.site) : -1;
    let rows = P.filter(p => (si < 0 || p.site === si) && (!state.issue || p.codes.includes(state.issue)) && (!state.links || p.links > 0) &&
      (!state.visits || p.visits > 0 || p.aclicks > 0 || p.gimpr > 0) && (!needle || p.url.toLowerCase().includes(needle)));
    const col = PAGE_COLS.find(c => c.key === state.sort) || PAGE_COLS[PAGE_COLS.length - 1], sign = state.dir === "asc" ? 1 : -1;
    rows.sort((a, b) => { const x = col.sort(a), y = col.sort(b); return (x < y ? -1 : x > y ? 1 : 0) * sign || b.score - a.score; });
    const last = Math.max(1, Math.ceil(rows.length / PER)), page = Math.min(last, Math.max(1, +state.p || 1));
    const hint = state.issue && issue(state.issue).action ? `<p class="small" style="margin:0 0 12px">${status(issue(state.issue).severity)} &nbsp;<span class="muted">${esc(issue(state.issue).action)}</span></p>` : "";
    box.innerHTML = hint + table(rows.slice((page - 1) * PER, page * PER), PAGE_COLS, { sort: col.key, dir: state.dir, sortable: true }) +
      `<div class="pager"><span>${plural(rows.length, "page")}${rows.length !== P.length ? ` of ${num(P.length)}` : ""}</span>
        <button class="btn" data-go="${page - 1}"${page <= 1 ? " disabled" : ""}>Previous</button><span>Page ${page} of ${last}</span><button class="btn" data-go="${page + 1}"${page >= last ? " disabled" : ""}>Next</button></div>`;
    const keep = Object.entries(state).filter(([k, v]) => v && !(k === "sort" && v === "score") && !(k === "dir" && v === "desc") && !(k === "p" && v === "1"));
    history.replaceState(null, "", "#/pages" + (keep.length ? "?" + new URLSearchParams(keep) : ""));
  };
  form.addEventListener("input", () => {
    const f = new FormData(form);
    Object.assign(state, { q: f.get("q") || "", site: f.get("site") || "", issue: f.get("issue") || "", links: f.get("links") ? "1" : "", visits: f.get("visits") ? "1" : "", p: "1" });
    draw();
  });
  box.addEventListener("click", e => {
    const sort = e.target.closest("[data-sort]"), go = e.target.closest("[data-go]");
    if (sort) { const k = sort.dataset.sort; state.dir = state.sort === k && state.dir === "desc" ? "asc" : "desc"; state.sort = k; state.p = "1"; draw(); }
    if (go && !go.disabled) { state.p = go.dataset.go; draw(); box.scrollIntoView({ block: "start" }); }
  });
  draw();
};

/* ---------- Work queue ---------- */
function queue() {
  const done = QUEUE.filter(p => FIXED.get(p.url)?.status === "fixed").length;
  const body = QUEUE.length ? table(QUEUE, QUEUE_COLS, {}) : `<p class="muted">No page has both measured demand and a gap to close. Add Search Console or analytics data (see Controls) so pages can be ranked.</p>`;
  return head("Work queue", `${plural(QUEUE.length, "page")} where measured demand meets a gap in Amazon links, highest priority first${done ? ` · ${done} already fixed by the engine` : ""}`,
      `<a class="btn" href="#/pages">All pages</a>`) +
    `<section class="card"><div class="bd" style="padding-top:18px">${body}
      <p class="small muted" style="margin-top:12px">Priority = clicks the page could reach, times how much of its Amazon potential is unused. Pages without Search Console or analytics data cannot be ranked and are not listed.</p></div></section>`;
}

/* ---------- Activity ---------- */
function fixTable(rows, showSite = true) {
  return `<div class="scroll"><table><thead><tr><th>Page</th><th>Change</th><th>Result</th></tr></thead><tbody>${rows.map(f => {
    let path = f.url; try { path = new URL(f.url).pathname; } catch {}
    const name = D.sites.find(s => s.domain === f.site)?.name || f.site;
    return `<tr><td><a class="path" href="${esc(f.url)}" target="_blank" rel="noopener">${esc(path)}</a>${showSite ? `<span class="sub">${esc(name)}</span>` : ""}</td>
      <td>${esc((f.changes || f.fixes || "").replace(/_/g, " ").replace(/=/g, ": ").replace(/;/g, ", "))}</td>
      <td>${f.status === "fixed" ? status("good", "Live") : status("warning", "Saved, not visible on the live page")}${f.still_failing_on_live_page ? `<span class="sub">Still found: ${esc(f.still_failing_on_live_page.split(" ").map(c => issue(c).label).join(", "))}</span>` : ""}</td></tr>`;
  }).join("")}</tbody></table></div>`;
}
function activity() {
  const subs = D.submissions.length ? `<div class="scroll"><table><thead><tr><th>Site</th><th class="n">New or changed</th><th class="n">Unchanged</th><th class="n">Total submitted</th><th>Result</th></tr></thead><tbody>${D.submissions.map(r => {
    const s = D.sites.find(x => x.domain === r.site), okay = r.status === "submitted" || r.status === "nothing_new";
    return `<tr><td><a href="#/site/${esc(r.site)}">${esc(s?.name || r.site)}</a></td><td class="n">${num(+r.urls_new_or_changed || 0)}</td><td class="n">${num(+r.urls_unchanged || 0)}</td><td class="n">${num(r.total)}</td><td>${status(okay ? "good" : "warning", r.detail || r.status.replace(/_/g, " "))}</td></tr>`;
  }).join("")}</tbody></table></div>` : `<p class="muted">No submission was recorded in this report.</p>`;
  const live = D.fixes.filter(f => f.status === "fixed").length;
  return head("Activity", `What the engine changed and sent in the report of ${day(D.generated)}`) +
    `<div class="stack">
      <div class="tiles">
        ${tile("Page changes live", num(live))}
        ${tile("Saved but not visible", num(D.fixes.length - live), D.fixes.length - live ? "Another plugin rewrites these at display time" : "")}
        ${tile("Pages sent this run", num(sum(D.submissions, r => +r.urls_new_or_changed)), "New or changed since the last submission")}
        ${tile("Pages submitted in total", num(sum(D.sites, s => s.submitted)))}
      </div>
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
      <article class="card"><div class="bd prose" style="padding-top:20px">${cur.html}</div></article></div>`;
}

/* ---------- Controls ---------- */
function controls() {
  const repo = D.repository;
  const action = (title, text, link) => `<div class="card action"><h3>${esc(title)}</h3><p>${text}</p><div>${link}</div></div>`;
  const cmd = text => `<div class="cmd"><span>${esc(text)}</span><button type="button" data-copy="${esc(text)}">Copy</button></div>`;
  const pick = (id, base, label, tail = "") => `<div class="filters" style="margin:0"><select id="${id}" aria-label="Site">${D.sites.map(s => `<option value="${esc(s.domain)}">${esc(s.name)}</option>`).join("")}</select><a class="btn" data-base="${esc(base)}" data-tail="${esc(tail)}" data-pick="${id}" href="${esc(base + D.sites[0].domain + tail)}" target="_blank" rel="noopener">${esc(label)}${icon("ext")}</a></div>`;
  const auto = D.auto_fix.length ? `<ul class="steps">${D.auto_fix.map(f => `<li><b>${esc(f)}</b> ${esc(FIX_LABEL[f] || "")}</li>`).join("")}</ul>` : `<p class="muted">No fix is switched on. The engine only reports.</p>`;
  if (!repo) return head("Controls", "The repository address is not known, so the action links cannot be built. Add <code>repository: owner/name</code> to <code>sites.yaml</code>.");
  return head("Controls", `Everything here opens the real control in GitHub, in <a href="${gh("")}" target="_blank" rel="noopener">${esc(repo)}</a>. This dashboard itself changes nothing.`) +
    `<div class="stack">
      <div class="actions">
        ${action("Run the engine now", "Crawls every site, scores pages, applies the switched-on fixes and submits changed pages. On the page that opens, choose <b>Run workflow</b>. You can untick fixes or submissions for a report-only run.", ext(gh("/actions/workflows/weekly-audit.yml"), "Open the workflow", "btn primary"))}
        ${action("See past runs", "Every run with its log, including what was changed and anything that failed. The engine also runs by itself every Monday at 05:17 UTC.", ext(gh("/actions"), "Open run history"))}
        ${action("Change sites and rules", "Sites, tracking IDs, blocked products and which fixes the engine may apply on its own all live in one file.", ext(gh("/edit/main/sites.yaml"), "Edit sites.yaml"))}
        ${action("Write a product box for a page", "A hand-written box always wins over a generated one. Name the file after the page's last URL part, ending in <code>.html</code>.", pick("box-site", gh("/new/main?filename=boxes/"), "New box", "/page-slug.html"))}
        ${action("Add Search Console data", "Upload a Pages export as <code>pages.csv</code>. Pages can then be ranked by real Google demand.", pick("gsc-site", gh("/upload/main/data/gsc/"), "Upload"))}
        ${action("Add analytics data", "Upload <code>amazon_clicks.csv</code> and <code>sessions.csv</code> so the engine knows which pages send people to Amazon.", pick("ga-site", gh("/upload/main/data/ga4/"), "Upload"))}
        ${action("Add Amazon Associates reports", "Upload the tracking ID summary so earnings can be set beside clicks.", ext(gh("/upload/main/data/associates"), "Upload"))}
        ${action("Logins the engine uses", "Stored as encrypted GitHub secrets, never in the repository. This dashboard cannot see which ones exist.", ext(gh("/settings/secrets/actions"), "Open secrets"))}
      </div>
      <div class="grid cols-2">
        ${card("What the engine fixes on its own", auto + `<p class="small muted" style="margin-top:12px">Set by <code>auto_fix</code> in sites.yaml. Fixes are only applied on sites whose login secret exists.</p>`)}
        ${card("Secrets it looks for", `<ul class="steps">
            <li><b>WP_AUTH_&lt;DOMAIN&gt;</b> one per WordPress site, as <code>username:application password</code>. Without it the site is audited but never edited.</li>
            <li><b>INDEXNOW_KEY</b> lets the weekly run submit new and changed pages to search engines.</li>
            <li><b>GSC_SERVICE_ACCOUNT_JSON</b> lets the weekly run pull Search Console data itself.</li>
          </ul>`)}
      </div>
      ${card("Downloads from this report", `<p style="display:flex;flex-wrap:wrap;gap:8px">${[["pages.csv", "All pages"], ["links.csv", "All Amazon links"], ["fix-log.csv", "Changes made"], ["indexnow-log.csv", "Submissions"], ["summary.md", "Full report"]].map(([f, l]) => `<a class="btn" href="downloads/${f}" download>${l}</a>`).join("")}</p>`)}
      ${card("Run it on your own computer", `<div class="stack" style="gap:8px">${cmd("python -m ace run")}${cmd("python -m ace fix")}${cmd("python -m ace fix --apply")}${cmd("python -m ace submit --apply")}${cmd("python -m ace site --site-out dist")}</div>
        <p class="small muted" style="margin-top:12px"><code>fix</code> and <code>submit</code> only show what they would do until <code>--apply</code> is added.</p>`)}
    </div>`;
}
controls.after = () => {
  view.querySelectorAll("[data-pick]").forEach(a => {
    const sel = $("#" + a.dataset.pick);
    sel.addEventListener("change", () => (a.href = a.dataset.base + sel.value + a.dataset.tail));
  });
};
view.addEventListener("click", async e => {
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch { b.textContent = "Select and copy"; }
  setTimeout(() => (b.textContent = "Copy"), 1600);
});

/* ---------- tooltip ---------- */
function showTip(el, x, y) {
  tip.innerHTML = el.dataset.tip;
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(x + 12, innerWidth - r.width - 8)) + "px";
  tip.style.top = (y + 16 + r.height > innerHeight ? y - r.height - 10 : y + 16) + "px";
}
document.addEventListener("mousemove", e => { const el = e.target.closest?.("[data-tip]"); el ? showTip(el, e.clientX, e.clientY) : (tip.hidden = true); });
document.addEventListener("focusin", e => { const el = e.target.closest?.("[data-tip]"); if (el) { const r = el.getBoundingClientRect(); showTip(el, r.left, r.bottom - 8); } });
document.addEventListener("focusout", () => (tip.hidden = true));
document.addEventListener("scroll", () => (tip.hidden = true), { passive: true });

/* ---------- theme ---------- */
$("#theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("ace-theme", root.dataset.theme); } catch {}
});

/* ---------- start ---------- */
fetch("data.json", { cache: "no-cache" })
  .then(r => { if (!r.ok) throw new Error("data.json: HTTP " + r.status); return r.json(); })
  .then(data => {
    prepare(data);
    $("#brand-date").textContent = "Report of " + day(D.generated);
    addEventListener("hashchange", render);
    render();
  })
  .catch(err => { view.innerHTML = `<div class="card"><div class="bd" style="padding-top:18px"><h2>The report could not be loaded</h2><p class="muted" style="margin-top:6px">${esc(err.message)}. Rebuild with <code>python -m ace site</code>.</p></div></div>`; });
})();
