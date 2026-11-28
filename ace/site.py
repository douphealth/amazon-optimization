"""Build the dashboard: a static single-page app plus one data file, for Cloudflare Pages or any host.

    python -m ace site --site-out dist

The build only reads files already in the repository (reports/, docs/, data/). It never crawls or
contacts a website, so it is fast and cannot fail on network errors. Standard library only.

Output: index.html, app.css, app.js (copied from ace/dashboard/), data.json, links.json and
queries.json (built here). links.json and queries.json are loaded only when a page is opened.
"""
from __future__ import annotations

import csv
import html
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit

from .fixer import CLEARS
from .config import norm_url
from .report import INDEXATION, ISSUE_TEXT

ASSETS = Path(__file__).parent / "dashboard"

# How serious each finding is, and what to do about it. Shown beside every flagged page.
SEVERITY = {
    "untagged_link": "critical", "foreign_tag": "critical", "earning_page_noindexed": "critical",
    "blocked_product": "serious", "no_disclosure": "serious", "first_link_very_late": "serious",
    "other_site_tag": "warning", "first_link_late": "warning", "search_links_only": "warning",
    "short_link": "warning", "missing_rel_sponsored": "warning", "cloaked_links": "warning",
    "low_serp_ctr": "warning", "no_meta_description": "warning",
    "demand_page_not_in_google": "serious", "low_bing_ctr": "warning", "not_in_google": "warning",
    "google_canonical_mismatch": "warning", "bing_crawl_error": "warning", "google_verdict_outdated": "warning",
}
ACTION = {
    "untagged_link": "Add the site's tracking ID to the link. Until then a sale through it earns nothing.",
    "foreign_tag": "Replace the tracking ID: it belongs to another Associates account.",
    "earning_page_noindexed": "Remove the noindex from this page. Visitors buy through it, and search engines are being told to drop it.",
    "blocked_product": "Point the link at a product that is still sold. The fixer does this when `blocked` is in auto_fix.",
    "no_disclosure": "Add an affiliate disclosure near the top of the page.",
    "first_link_very_late": "Add a product box near the top. The fixer does this for pages with visitors.",
    "first_link_late": "Move a product link or box higher in the article.",
    "other_site_tag": "Use this site's own tracking ID so its clicks show up separately in Associates reports.",
    "search_links_only": "Link to specific products as well as Amazon searches.",
    "short_link": "Replace amzn.to links with full Amazon links so the tracking ID can be checked.",
    "missing_rel_sponsored": "Add rel=\"sponsored nofollow\" to the Amazon link.",
    "cloaked_links": "Check that the redirect link makes clear it leads to Amazon.",
    "low_serp_ctr": "Rewrite the title and description to match what people search for.",
    "no_meta_description": "Write a meta description.",
    "no_amazon_links": "Only an issue if this page is about something people buy. If so, add relevant product links.",
    "noindex": "Intended only if the page should stay out of search engines.",
    "canonical_elsewhere": "Check that the canonical URL is the page you want search engines to index.",
    "redirects": "Remove or update this URL in the sitemap.",
    "thin_content": "Expand the page or leave it out of the sitemap.",
    "near_duplicate": "Differentiate the page or consolidate it with its near-copies.",
    "duplicate_title": "Give the page its own title.",
    "demand_page_not_in_google": "People already reach this page from Bing or elsewhere; Google has not indexed it. Strengthen it, link to it from indexed pages, then request indexing in Search Console.",
    "not_in_google": "Google has not indexed this page. See the reason in the page panel; improve or consolidate the page, or link to it from pages Google has indexed.",
    "google_canonical_mismatch": "Google treats another URL as the main version of this page. Make the canonical, internal links and sitemap agree on one URL.",
    "google_verdict_outdated": "The page is indexable now. Ask Google to look again: Search Console > URL Inspection > Request indexing.",
    "bing_crawl_error": "Bing could not fetch this page. Open it, fix the error, then resubmit it in Bing Webmaster Tools.",
    "low_bing_ctr": "Rewrite the title and description so Bing searchers choose it.",
}
# What Google's URL Inspection states mean and what to do. Keys are Search Console's own wording.
COVERAGE_ADVICE = {
    "Submitted and indexed": "In Google's index.",
    "Indexed, not submitted in sitemap": "In Google's index, but missing from the sitemap Search Console reads. Add it.",
    "Crawled - currently not indexed": "Google read the page and chose not to index it. That is a quality or duplication signal: make the page clearly better than similar pages, or merge it into one.",
    "Discovered - currently not indexed": "Google knows the address but has not read the page yet. Usually a sign it does not value the site enough to crawl more: link to the page from indexed pages and cut low-value URLs.",
    "URL is unknown to Google": "Google has never seen this address. Check it is in a sitemap submitted in Search Console and linked from indexed pages.",
    "Duplicate, Google chose different canonical than user": "Google treats another URL as the main version. Make the canonical, internal links and sitemap agree.",
    "Duplicate without user-selected canonical": "Google sees this as a copy of another page and the page names no canonical. Add one, or make the page distinct.",
    "Alternate page with proper canonical tag": "Excluded on purpose: the page points to another canonical URL.",
    "Excluded by ‘noindex’ tag": "The page tells Google not to index it.",
    "Page with redirect": "The address redirects. Keep only the final URL in sitemaps and links.",
    "Soft 404": "Google thinks the page is empty or an error page. Add real content or return a 404/410.",
    "Not found (404)": "The page returns 404. Restore it or redirect it to the closest page.",
    "Blocked by robots.txt": "robots.txt stops Google from reading the page.",
    "Server error (5xx)": "The server returned an error when Google tried to read the page.",
}
SHORT = {
    "untagged_link": "No tracking ID", "foreign_tag": "Another account's ID", "earning_page_noindexed": "Earning but noindexed",
    "blocked_product": "Blocked product", "no_disclosure": "No disclosure", "first_link_very_late": "First link in bottom half",
    "first_link_late": "First link 30-50% down", "other_site_tag": "Other site's ID", "search_links_only": "Search links only",
    "short_link": "amzn.to short link", "missing_rel_sponsored": "No rel=sponsored", "cloaked_links": "Cloaked links",
    "low_serp_ctr": "Low click-through", "no_meta_description": "No meta description",
    "demand_page_not_in_google": "Demand, not in Google", "not_in_google": "Not in Google",
    "google_canonical_mismatch": "Google picked another URL", "bing_crawl_error": "Bing crawl error", "google_verdict_outdated": "Google verdict out of date", "low_bing_ctr": "Low Bing click-through",
}
MONEY = {"demand_page_not_in_google",
    
    "untagged_link", "foreign_tag", "other_site_tag", "short_link", "missing_rel_sponsored", "no_disclosure",
    "search_links_only", "cloaked_links", "blocked_product", "earning_page_noindexed", "first_link_very_late",
    "first_link_late", "no_amazon_links",
}

# Findings that cost clicks or commission and call for a change (the neutral "note" ones are left out).
TO_FIX = {c for c in MONEY if SEVERITY.get(c, "info") != "info"}
# Which automatic fix clears each finding. A page with no Amazon link only gets a box when someone
# has written one for it, so that finding is not listed as automatic.
FIX_FOR = {code: name for name, codes in CLEARS.items() for code in codes if code != "no_amazon_links"}
TREND = ("pages", "with_links", "links", "late", "to_fix")

INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), r'<a href="\2" target="_blank" rel="noopener">\1</a>'),
    (re.compile(r"(?<![\"'>=])\b(https?://[^\s<|)]+)"), r'<a href="\1" target="_blank" rel="noopener">\1</a>'),
]


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    for pattern, repl in INLINE:
        text = pattern.sub(repl, text)
    return text


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown(text: str, max_rows: int | None = None) -> str:
    """Render the Markdown subset the reports use: headings, paragraphs, lists, tables, code fences."""
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    item = re.compile(r"\s*(?:[-*]|\d+\.)\s+")
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        heading = re.match(r"(#{1,4})\s+(.*)", line)
        if heading:
            level = len(heading.group(1))
            slug = re.sub(r"[^a-z0-9]+", "-", heading.group(2).lower()).strip("-")
            out.append(f'<h{level} id="{slug}">{inline(heading.group(2))}</h{level}>')
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = _cells(line)
            j = i + 2
            rows = []
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_cells(lines[j]))
                j += 1
            shown = rows[:max_rows] if max_rows else rows
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in shown)
            out.append(
                '<div class="scroll"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head)
                + f"</tr></thead><tbody>{body}</tbody></table></div>"
            )
            if max_rows and len(rows) > max_rows:
                out.append(f'<p class="muted">Showing {max_rows} of {len(rows)} rows.</p>')
            i = j
            continue
        if item.match(line):
            tag = "ol" if re.match(r"\s*\d+\.", line) else "ul"
            items: list[str] = []
            while i < len(lines) and (item.match(lines[i]) or (lines[i].startswith("  ") and lines[i].strip() and items)):
                if item.match(lines[i]):
                    items.append(item.sub("", lines[i], count=1))
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        para = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,4}\s|\s*\||```|\s*(?:[-*]|\d+\.)\s+)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(out)


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _num(value) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


def report_dirs(root: Path) -> list[Path]:
    return sorted(d for d in root.iterdir() if d.is_dir() and (d / "pages.csv").exists()) if root.exists() else []


def repository_public(slug: str) -> bool | None:
    """Whether GitHub shows the repository to anyone (True), hides it (False), or could not say (None).
    The dashboard skips its live run lookup for a private repository: the browser could never read it."""
    if not slug:
        return None
    try:
        import requests
        resp = requests.get(f"https://api.github.com/repos/{slug}", headers={"Accept": "application/vnd.github+json"}, timeout=8)
    except Exception:
        return None
    if resp.status_code == 404:
        return False
    if resp.ok:
        return not resp.json().get("private", False)
    return None


def repository_slug(cfg=None) -> str:
    """owner/name of the GitHub repository, for the dashboard's action links."""
    if cfg is not None and getattr(cfg, "repository", ""):
        return cfg.repository
    try:
        url = subprocess.run(["git", "config", "--get", "remote.origin.url"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?\s*$", url)
        return m.group(1) if m else ""
    except Exception:
        return ""


def site_stats(rows: list[dict]) -> dict:
    """Roll one site's page rows up into the numbers the dashboard shows."""
    ok = [r for r in rows if r.get("status") == "200"]
    linked = [r for r in ok if _num(r.get("amazon_links")) > 0]
    depths = [_num(r["first_link_depth"]) for r in linked if r.get("first_link_depth") not in (None, "")]
    issues = Counter(code for r in rows for code in (r.get("issues") or "").split())
    return {
        "pages": len(rows), "ok": len(ok), "with_links": len(linked),
        "links": int(sum(_num(r.get("amazon_links")) for r in ok)),
        "early": sum(1 for r in linked if r.get("first_link_depth") not in (None, "") and _num(r["first_link_depth"]) < 0.30),
        "late": sum(1 for r in linked if r.get("first_link_depth") not in (None, "") and _num(r["first_link_depth"]) >= 0.30),
        "median_depth": round(median(depths), 3) if depths else None,
        "noindex": issues.get("noindex", 0),
        "to_fix": sum(1 for r in rows if TO_FIX & set((r.get("issues") or "").split())),
        "ga_clicks": int(sum(_num(r.get("ga_amazon_clicks")) for r in rows)),
        "ga_sessions": int(sum(_num(r.get("ga_sessions")) for r in rows)),
        "gsc_clicks": int(sum(_num(r.get("gsc_clicks")) for r in rows)),
        "gsc_impressions": int(sum(_num(r.get("gsc_impressions")) for r in rows)),
        "gsc_pages": sum(1 for r in rows if r.get("gsc_impressions") not in (None, "")),
        "bing_clicks": int(sum(_num(r.get("bing_clicks")) for r in rows)),
        "bing_impressions": int(sum(_num(r.get("bing_impressions")) for r in rows)),
        "bing_pages": sum(1 for r in rows if r.get("bing_impressions") not in (None, "")),
        "google_inspected": sum(1 for r in ok if r.get("google_verdict") not in (None, "", "ERROR")),
        "google_indexed": sum(1 for r in ok if r.get("google_verdict") == "PASS"),
        "coverage": dict(Counter(r["google_index"] for r in ok if r.get("google_index") and r.get("google_verdict") != "ERROR")),
        "issues": dict(issues),
    }


COLS = [
    "site", "url", "status", "words", "commercial", "links", "product", "search", "depth", "tags",
    "gclicks", "gimpr", "gpos", "sessions", "aclicks", "score", "dup", "issues",
    "bclicks", "bimpr", "bpos", "gverdict", "gidx", "gcrawl",
]


def _page_row(r: dict, site_index: dict[str, int]) -> list:
    def n(key, digits=None):
        v = r.get(key)
        if v in (None, ""):
            return None
        f = _num(v)
        return round(f, digits) if digits else (int(f) if f == int(f) else f)

    return [
        site_index[r["site"]], r["url"], int(_num(r.get("status"))), n("words"), int(_num(r.get("commercial_intent"))),
        n("amazon_links") or 0, n("product_links") or 0, n("search_links") or 0, n("first_link_depth", 3), r.get("tags") or "",
        n("gsc_clicks"), n("gsc_impressions"), n("gsc_position", 1), n("ga_sessions"), n("ga_amazon_clicks"),
        n("score", 2) or 0, n("near_duplicate_group"), r.get("issues") or "",
        n("bing_clicks"), n("bing_impressions"), n("bing_position", 1), r.get("google_verdict") or "", r.get("google_index") or "",
        r.get("google_last_crawl") or "",
    ]


def _pages(n: int) -> str:
    return f"{n} page" if n == 1 else f"{n} pages"


def _have(n: int) -> str:
    return "has" if n == 1 else "have"


def attention(sites: list[dict], pages: list[dict]) -> list[dict]:
    """The short list of things that most deserve a decision, worst first. Every item is counted from data."""
    items: list[dict] = []
    total = Counter(code for r in pages for code in (r.get("issues") or "").split())

    def add(severity, title, detail, issue=None):
        items.append({"severity": severity, "title": title, "detail": detail, "issue": issue})

    if total["earning_page_noindexed"]:
        n = total["earning_page_noindexed"]
        add("critical", f"{n} page{'s' if n != 1 else ''} earning Amazon clicks {'are' if n != 1 else 'is'} hidden from search engines",
            "Visitors buy through these pages, but a noindex tag tells search engines to drop them.", "earning_page_noindexed")
    if total["demand_page_not_in_google"]:
        n = total["demand_page_not_in_google"]
        add("serious", f"{_pages(n)} with search demand {'are' if n != 1 else 'is'} not in Google's index",
            "They get visits, Amazon clicks or at least 20 Bing impressions in four weeks, yet Google has not indexed them (URL Inspection).",
            "demand_page_not_in_google")
    weak = [s for s in sites if s.get("google_inspected", 0) >= 20 and s["google_indexed"] < 0.5 * s["google_inspected"]]
    if weak:
        add("serious", f"Google has indexed under half the pages on {len(weak)} site{'s' if len(weak) != 1 else ''}",
            "; ".join(f"{s['name']} {s['google_indexed']} of {s['google_inspected']}" for s in sorted(weak, key=lambda s: s['google_indexed'] / s['google_inspected']))
            + ". Pages outside the index cannot earn from Google.", "not_in_google")
    for s in sites:
        health = s.get("ga_health")
        if health:
            add("warning", f"{s['name']}: {health['title']}", health["detail"])
    if total["untagged_link"]:
        n = total["untagged_link"]
        add("critical", f"{n} page{'s' if n != 1 else ''} with an Amazon link that has no tracking ID",
            "A sale through an untagged link earns nothing.", "untagged_link")
    if total["foreign_tag"]:
        add("critical", f"{_pages(total['foreign_tag'])} {'links' if total['foreign_tag'] == 1 else 'link'} to Amazon with another account's tracking ID",
            "Commission from these links goes to someone else.", "foreign_tag")
    if total["blocked_product"]:
        add("serious", f"{_pages(total['blocked_product'])} link to a product marked as wrong or gone",
            "The link lands on something other than what the page promises.", "blocked_product")
    if total["no_disclosure"]:
        add("serious", f"{_pages(total['no_disclosure'])} {_have(total['no_disclosure'])} Amazon links and no affiliate disclosure",
            "An affiliate statement is required wherever affiliate links appear.", "no_disclosure")
    if total["other_site_tag"]:
        add("warning", f"{_pages(total['other_site_tag'])} {'uses' if total['other_site_tag'] == 1 else 'use'} a tracking ID that is not {'its' if total['other_site_tag'] == 1 else 'their'} site's",
            "Their clicks cannot be told apart in Amazon Associates reports.", "other_site_tag")
    blind = [s["name"] for s in sites if not s["has_gsc"]]
    if blind:
        add("warning", f"No Search Console data for {len(blind)} site{'s' if len(blind) != 1 else ''}",
            ", ".join(blind) + ". Pages there are audited but cannot be ranked by Google demand.")
    unsent = [s["name"] for s in sites if not s["submitted"]]
    if unsent:
        add("warning", f"{len(unsent)} site{'s' if len(unsent) != 1 else ''} not yet submitted to search engines", ", ".join(unsent) + ".")
    if total["first_link_very_late"]:
        add("warning", f"{_pages(total['first_link_very_late'])} {_have(total['first_link_very_late'])} {'its' if total['first_link_very_late'] == 1 else 'their'} first Amazon link in the bottom half",
            "Most readers leave before reaching it. The fixer adds a box on pages that have visitors.", "first_link_very_late")
    return items


def _daily(path: Path, key: str = "clicks") -> dict[str, float]:
    return {r["date"]: _num(r.get(key)) for r in _csv(path)}


def service_account_email() -> str:
    """The Google service account's email, if a key is available, so warnings can say whom to add."""
    try:
        from . import gcp
        return (gcp.service_account_info() or {}).get("client_email", "")
    except Exception:
        return ""


def search_trend(domain: str, gsc: Path, bing: Path, days: int = 90) -> dict:
    """Daily clicks and impressions from Google and Bing for the last `days` days either has data.
    A day an engine has not reported yet is None, not zero."""
    g, b = _csv(gsc / domain / "daily.csv"), _csv(bing / domain / "daily.csv")
    gd = {r["date"]: r for r in g}
    bd = {r["date"]: r for r in b}
    last = max([*gd, *bd], default=None)
    if not last:
        return {}
    from datetime import date, timedelta
    end = date.fromisoformat(last)
    dates = [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    g_end, b_end = max(gd, default=""), max(bd, default="")
    col = lambda src, d, k, end_: (int(_num(src[d][k])) if d in src else (0 if src and d <= end_ else None))
    return {"dates": dates,
            "google": [col(gd, d, "clicks", g_end) for d in dates], "bing": [col(bd, d, "clicks", b_end) for d in dates],
            "google_impr": [col(gd, d, "impressions", g_end) for d in dates], "bing_impr": [col(bd, d, "impressions", b_end) for d in dates]}


def window_total(daily: list[dict], start: str | None, end: str | None, key: str) -> int | None:
    if not start or not end:
        return None
    return int(sum(_num(r.get(key)) for r in daily if start <= r["date"] <= end))


def ga_health(meta: dict | None, search_clicks: int | None, sa_email: str = "") -> dict | None:
    """A warning when Analytics cannot be trusted for this site, naming the cause when it is known:
    no tag on the site, a tag that sends data to a property the service account cannot read, no
    visits recorded, or far fewer organic visits than the search engines report sending."""
    if meta is None:
        return None
    sa_email = sa_email or meta.get("service_account", "")
    who = f" ({sa_email})" if sa_email else ""
    tags = meta.get("tags") or {}
    unreadable = meta.get("unreadable_tags") or []
    # A script-loaded or optimised tag can hide its ID from the HTML, so "no tag" also needs near-zero visits.
    if tags.get("checked") and not tags.get("ga") and not tags.get("gtm") and not tags.get("other") and (meta.get("sessions") or 0) < 100:
        return {"title": "No Analytics tag on the site",
                "detail": f"The homepage loads no Google Analytics or Tag Manager tag, so visits and Amazon clicks go unrecorded. "
                          f"Add the tag for property {meta.get('property') or 'of this site'} in the site's header scripts."}
    if not meta.get("sessions") and unreadable:
        return {"title": "Analytics reads the wrong property",
                "detail": f"The site's tag sends data to {', '.join(unreadable)}, a property the engine cannot read. "
                          f"In Google Analytics, open the property with that measurement ID and add the service account{who} as a Viewer "
                          "under Admin > Property access management. The next run finds it automatically."}
    if not meta.get("sessions"):
        notes = "; ".join(meta.get("notes", [])) or f"property {meta.get('property')} recorded no sessions"
        return {"title": "Analytics records no visits",
                "detail": notes[:1].upper() + notes[1:] + ". Check that the site's Google tag is installed and firing."}
    organic = meta.get("organic_sessions") or 0
    if search_clicks and search_clicks >= 30 and organic < 0.3 * search_clicks:
        return {"title": "Analytics misses most search visits",
                "detail": f"Google and Bing report {search_clicks} clicks in 28 days; Analytics recorded {organic} organic sessions. "
                          "The tag is probably missing on some pages or blocked by the consent banner, so page rankings on this site rely on search data."}
    return None


def queries_by_page(domains: list[str], urls: list[str], gsc: Path, bing: Path) -> dict[str, dict]:
    """{page url: {"g": [[query, clicks, impressions, position], ...], "b": [...]}} for the page panel."""
    keyed = {norm_url(u): u for u in urls}
    merged: dict[tuple, list] = {}
    for d in domains:
        for engine, path in (("g", gsc / d / "queries.csv"), ("b", bing / d / "page_queries.csv")):
            for r in _csv(path):
                url = keyed.get(norm_url(r.get("page", "")))
                if not url:
                    continue
                # Search Console lists #section jump links as separate pages: merge them into the page.
                m = merged.setdefault((url, engine, r["query"]), [0, 0, 0.0])
                clicks, impr, pos = _num(r["clicks"]), _num(r["impressions"]), _num(r.get("position"))
                m[0] += clicks
                m[1] += impr
                m[2] += pos * impr
    out: dict[str, dict] = {}
    for (url, engine, query), (clicks, impr, weighted) in merged.items():
        out.setdefault(url, {}).setdefault(engine, []).append([query, int(clicks), int(impr), round(weighted / impr, 1) if impr else None])
    for engines in out.values():
        for engine, rows in engines.items():
            engines[engine] = sorted(rows, key=lambda r: (-r[1], -r[2]))[:10]
    return out


def schedule(workflow: Path = Path(".github/workflows/weekly-audit.yml")) -> str:
    """The cron line of the scheduled run, e.g. "17 5 * * 1", or "" when there is none."""
    m = re.search(r'cron:\s*"([^"]+)"', workflow.read_text()) if workflow.exists() else None
    return m.group(1) if m else ""


def _product_boxes() -> dict:
    """Live product boxes (data/products/boxes.json): page URL -> product names and where each came from."""
    path = Path("data/products/boxes.json")
    reg = json.loads(path.read_text()) if path.exists() else {}
    return {url: {"names": r.get("names", []), "sources": r.get("sources", []), "run": r.get("run", "")} for url, r in reg.items()}


def _box_plan() -> dict:
    """How many pages the product plan gives a box, and each such page's topic."""
    path = Path("data/products/plan.json")
    plan = json.loads(path.read_text()) if path.exists() else {}
    return {e["url"]: e.get("topic", "") for e in plan.values() if e.get("box")}


def _box_files(root: Path, urls: set[str], by_site: dict[str, list[dict]]) -> dict[str, str]:
    """{page url: repository path} for the box files under root/<domain>/, matched to audited pages."""
    found: dict[str, str] = {}
    for domain, site_rows in by_site.items():
        folder = root / domain
        if not folder.is_dir():
            continue
        names = {f.stem: f for f in folder.glob("*.html")}
        for r in site_rows:
            slug = urlsplit(r["url"]).path.strip("/").replace("/", "__") or "home"
            if slug in names and r["url"] in urls:
                found[r["url"]] = names[slug].as_posix()
    return found


def _sources(domain: str, gsc: Path, ga4: Path, bing: Path) -> dict:
    """What the dashboard knows about a site's search and analytics data, and how fresh it is."""
    gmeta = json.loads((gsc / domain / "meta.json").read_text()) if (gsc / domain / "meta.json").exists() else None
    bmeta = json.loads((bing / domain / "meta.json").read_text()) if (bing / domain / "meta.json").exists() else None
    ameta = json.loads((ga4 / domain / "meta.json").read_text()) if (ga4 / domain / "meta.json").exists() else None
    gdaily, bdaily = _csv(gsc / domain / "daily.csv"), _csv(bing / domain / "daily.csv")
    inspected = [r.get("inspected", "") for r in _csv(gsc / domain / "index.csv")]
    crawl = _csv(bing / domain / "crawl.csv")
    issues = _csv(bing / domain / "crawl_issues.csv")
    return {
        "has_bing": bmeta is not None and bool(bmeta.get("start")),
        "bing_window": bmeta,
        "google_clicks_28": window_total(gdaily, (gmeta or {}).get("start"), (gmeta or {}).get("end"), "clicks") if gdaily else None,
        "google_impr_28": window_total(gdaily, (gmeta or {}).get("start"), (gmeta or {}).get("end"), "impressions") if gdaily else None,
        "bing_clicks_28": window_total(bdaily, (bmeta or {}).get("start"), (bmeta or {}).get("end"), "clicks") if bdaily else None,
        "bing_impr_28": window_total(bdaily, (bmeta or {}).get("start"), (bmeta or {}).get("end"), "impressions") if bdaily else None,
        "bing_crawl": crawl[-1] if crawl else None,
        "bing_crawl_errors": sum(1 for r in issues if set(r.get("issues", "").split()) & {"4xx", "5xx", "timeout", "dns_error", "blocked_by_robots"}),
        "ga": ameta,
        "ga_sources": _csv(ga4 / domain / "sources.csv")[:10],
        "inspected_at": max(inspected) if inspected else None,
        "sitemaps": _csv(gsc / domain / "sitemaps.csv"),
        "trend": search_trend(domain, gsc, bing),
    }


def links_by_page(report: Path) -> dict[str, list[list]]:
    """{page url: [[href, kind, tracking id, product id, name], ...]} for the page detail panel."""
    out: dict[str, list[list]] = {}
    for r in _csv(report / "links.csv"):
        if r.get("in_site_chrome") == "1":
            continue
        out.setdefault(r["page"], []).append([r["href"], r.get("kind", ""), r.get("tag", ""), r.get("asin", ""), r.get("name", "")])
    return out


def all_fixes(dirs: list[Path]) -> list[dict]:
    """Every page change the engine made, from every report, newest report first; one row per page
    (its most recent change)."""
    seen, out = set(), []
    for folder in reversed(dirs):
        for r in _csv(folder / "fix-log.csv"):
            if r.get("status") in ("fixed", "saved_but_live_page_unchanged") and r["url"] not in seen:
                seen.add(r["url"])
                out.append({**r, "report": folder.name})
    return out


def build_data(cfg=None, reports: Path = Path("reports"), docs: Path = Path("docs"), state: Path = Path("data/indexnow"),
               gsc: Path = Path("data/gsc"), ga4: Path = Path("data/ga4"), bing: Path = Path("data/bing")) -> dict:
    dirs = report_dirs(reports)
    if not dirs:
        raise SystemExit(f"No report with a pages.csv found under {reports}/")
    report = dirs[-1]
    rows = _csv(report / "pages.csv")
    previous = dirs[-2] if len(dirs) > 1 else None
    prev_by_site: dict[str, list[dict]] = {}
    for r in (_csv(previous / "pages.csv") if previous else []):
        prev_by_site.setdefault(r["site"], []).append(r)

    domains = list(dict.fromkeys([s.domain for s in cfg.sites] if cfg else []) | dict.fromkeys(r["site"] for r in rows))
    # One point per report, oldest first, so the dashboard can draw trends once a few runs exist.
    history: dict[str, list[dict]] = {d: [] for d in domains}
    total_history = []
    for folder in dirs:
        past = rows if folder == report else _csv(folder / "pages.csv")
        grouped: dict[str, list[dict]] = {}
        for r in past:
            grouped.setdefault(r["site"], []).append(r)
        whole = site_stats(past)
        total_history.append({"date": folder.name, **{k: whole[k] for k in TREND}})
        for d in domains:
            if d in grouped:
                stats = site_stats(grouped[d])
                history[d].append({"date": folder.name, **{k: stats[k] for k in TREND}})
    conf = {s.domain: s for s in cfg.sites} if cfg else {}
    by_site: dict[str, list[dict]] = {d: [] for d in domains}
    for r in rows:
        by_site[r["site"]].append(r)
    log = {r["site"]: r for r in _csv(report / "indexnow-log.csv")}

    sites = []
    for d in domains:
        s = site_stats(by_site[d])
        meta_path = gsc / d / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
        state_path = state / f"{d}.json"
        sent = json.loads(state_path.read_text()) if state_path.exists() else {}
        tags = Counter(t for r in by_site[d] for t in (r.get("tags") or "").split())
        s.update({
            "domain": d, "name": conf[d].name if d in conf else d,
            "expected_tags": list(conf[d].tags) if d in conf else [],
            "wordpress": bool(conf[d].wordpress) if d in conf else True,
            "tags_seen": dict(tags), "has_gsc": meta is not None, "gsc_window": meta,
            "gsc_property": conf[d].gsc_property if d in conf else "",
            "has_ga": any((ga4 / d / f).exists() for f in ("amazon_clicks.csv", "sessions.csv")),
            **_sources(d, gsc, ga4, bing),
            "submitted": len(sent.get("submitted", {})), "last_submission": sent.get("last_submission"),
            "submission_status": (log.get(d) or {}).get("detail", ""),
            "prev": site_stats(prev_by_site[d]) if d in prev_by_site else None,
            "history": history[d],
            "new_pages": len({r["url"] for r in by_site[d]} - {r["url"] for r in prev_by_site[d]}) if d in prev_by_site else None,
            "gone_pages": len({r["url"] for r in prev_by_site[d]} - {r["url"] for r in by_site[d]}) if d in prev_by_site else None,
        })
        s["ga_health"] = ga_health(s["ga"], (s["google_clicks_28"] or 0) + (s["bing_clicks_28"] or 0) if s["has_gsc"] or s["has_bing"] else None,
                                   service_account_email())
        sites.append(s)

    index = {d: i for i, d in enumerate(domains)}
    trends = [s["trend"] for s in sites if s.get("trend")]
    portfolio_trend = {}
    if trends:
        all_dates = sorted({d for tr in trends for d in tr["dates"]})[-90:]
        def total(key):
            vals = []
            for d in all_dates:
                parts = [tr[key][tr["dates"].index(d)] for tr in trends if d in tr["dates"]]
                known = [v for v in parts if v is not None]
                vals.append(sum(known) if known else None)
            return vals
        portfolio_trend = {"dates": all_dates, "google": total("google"), "bing": total("bing")}
    notes = []
    if (report / "summary.md").exists():
        notes.append({"slug": "full-report", "title": f"Full audit report, {report.name}", "html": markdown((report / "summary.md").read_text())})
    for n in sorted(docs.glob("*.md")) if docs.exists() else []:
        text = n.read_text()
        notes.append({"slug": n.stem, "title": text.splitlines()[0].lstrip("# ").strip() or n.stem, "html": markdown(text)})

    codes = sorted({c for r in rows for c in (r.get("issues") or "").split()} | set(ISSUE_TEXT))
    auto_fix = list(getattr(cfg, "auto_fix", []) or [])
    known = {r["url"] for r in rows}
    return {
        "generated": report.name, "previous": previous.name if previous else None,
        "repository": repository_slug(cfg),
        "repository_public": repository_public(repository_slug(cfg)),
        "auto_fix": auto_fix, "box_min_clicks": getattr(cfg, "box_min_clicks", 1),
        "schedule": schedule(), "history": total_history, "trend": portfolio_trend, "coverage_advice": COVERAGE_ADVICE,
        "last_run": json.loads(Path("data/last-run.json").read_text()) if Path("data/last-run.json").exists() else None,
        "pull_status": json.loads(Path("data/pull-status.json").read_text()) if Path("data/pull-status.json").exists() else None,
        "drafts": _box_files(report / "fixes", known, by_site), "boxes": _box_files(Path("boxes"), known, by_site),
        "product_boxes": _product_boxes(), "box_plan": _box_plan(),
        "sites": sites, "cols": COLS, "pages": [_page_row(r, index) for r in rows],
        "issues": {
            c: {
                "label": ISSUE_TEXT.get(c) or (f"sitemap URL returns HTTP {c[5:]}" if c.startswith("http_") else c.replace("_", " ")), "short": SHORT.get(c, ""), "severity": SEVERITY.get(c, "info"), "action": ACTION.get(c, ""),
                "group": "money" if c in MONEY else ("indexing" if c in INDEXATION else "search"),
                "to_fix": c in TO_FIX, "fix": FIX_FOR.get(c, ""), "fix_on": FIX_FOR.get(c) in auto_fix,
            } for c in codes
        },
        "attention": attention(sites, rows),
        "fixes": all_fixes(dirs),
        "submissions": [{**r, "total": sites[index[r["site"]]]["submitted"]} for r in _csv(report / "indexnow-log.csv") if r["site"] in index],
        "notes": notes,
    }


def build(out: Path, cfg=None, reports: Path = Path("reports"), docs: Path = Path("docs"), state: Path = Path("data/indexnow"),
          gsc: Path = Path("data/gsc"), ga4: Path = Path("data/ga4"), bing: Path = Path("data/bing"),
          mirrors: list[Path] | None = None) -> Path:
    data = build_data(cfg, reports, docs, state, gsc, ga4, bing)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for asset in sorted(ASSETS.iterdir()):
        if asset.is_file():
            shutil.copy(asset, out / asset.name)
    (out / "data.json").write_text(json.dumps(data, separators=(",", ":")))
    report = report_dirs(reports)[-1]
    (out / "links.json").write_text(json.dumps(links_by_page(report), separators=(",", ":")))
    domains = [s["domain"] for s in data["sites"]]
    urls = [row[1] for row in data["pages"]]
    (out / "queries.json").write_text(json.dumps(queries_by_page(domains, urls, gsc, bing), separators=(",", ":")))
    (out / "downloads").mkdir()
    for name in ("pages.csv", "links.csv", "fix-log.csv", "indexnow-log.csv", "summary.md"):
        if (report / name).exists():
            shutil.copy(report / name, out / "downloads" / name)
    # Ask search engines to stay away from this working dashboard.
    (out / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    # Hosting services differ in which folder they publish, so the same site can be written to several.
    for mirror in mirrors or []:
        if mirror.resolve() == out.resolve():
            continue
        if mirror.resolve() == Path.cwd().resolve():
            shutil.copytree(out, mirror, dirs_exist_ok=True)  # the project folder itself: add, never delete
            continue
        if mirror.exists():
            shutil.rmtree(mirror)
        shutil.copytree(out, mirror)
    return out
