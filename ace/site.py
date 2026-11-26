"""Build the dashboard: a static single-page app plus one data file, for Cloudflare Pages or any host.

    python -m ace site --site-out dist

The build only reads files already in the repository (reports/, docs/, data/). It never crawls or
contacts a website, so it is fast and cannot fail on network errors. Standard library only.

Output: index.html, app.css, app.js (copied from ace/dashboard/) and data.json (built here).
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

from .report import INDEXATION, ISSUE_TEXT

ASSETS = Path(__file__).parent / "dashboard"

# How serious each finding is, and what to do about it. Shown beside every flagged page.
SEVERITY = {
    "untagged_link": "critical", "foreign_tag": "critical", "earning_page_noindexed": "critical",
    "blocked_product": "serious", "no_disclosure": "serious", "first_link_very_late": "serious",
    "other_site_tag": "warning", "first_link_late": "warning", "search_links_only": "warning",
    "short_link": "warning", "missing_rel_sponsored": "warning", "cloaked_links": "warning",
    "low_serp_ctr": "warning", "no_meta_description": "warning",
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
}
MONEY = {
    "untagged_link", "foreign_tag", "other_site_tag", "short_link", "missing_rel_sponsored", "no_disclosure",
    "search_links_only", "cloaked_links", "blocked_product", "earning_page_noindexed", "first_link_very_late",
    "first_link_late", "no_amazon_links",
}

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
        "ga_clicks": int(sum(_num(r.get("ga_amazon_clicks")) for r in rows)),
        "ga_sessions": int(sum(_num(r.get("ga_sessions")) for r in rows)),
        "gsc_clicks": int(sum(_num(r.get("gsc_clicks")) for r in rows)),
        "gsc_impressions": int(sum(_num(r.get("gsc_impressions")) for r in rows)),
        "gsc_pages": sum(1 for r in rows if r.get("gsc_impressions") not in (None, "")),
        "issues": dict(issues),
    }


COLS = [
    "site", "url", "status", "words", "commercial", "links", "product", "search", "depth", "tags",
    "gclicks", "gimpr", "gpos", "sessions", "aclicks", "score", "dup", "issues",
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
    ]


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
    if total["untagged_link"]:
        n = total["untagged_link"]
        add("critical", f"{n} page{'s' if n != 1 else ''} with an Amazon link that has no tracking ID",
            "A sale through an untagged link earns nothing.", "untagged_link")
    if total["foreign_tag"]:
        add("critical", f"{total['foreign_tag']} pages link to Amazon with another account's tracking ID",
            "Commission from these links goes to someone else.", "foreign_tag")
    if total["blocked_product"]:
        add("serious", f"{total['blocked_product']} pages link to a product marked as wrong or gone",
            "The link lands on something other than what the page promises.", "blocked_product")
    if total["no_disclosure"]:
        add("serious", f"{total['no_disclosure']} pages have Amazon links and no affiliate disclosure",
            "An affiliate statement is required wherever affiliate links appear.", "no_disclosure")
    if total["other_site_tag"]:
        add("warning", f"{total['other_site_tag']} pages use a tracking ID that is not their site's",
            "Their clicks cannot be told apart in Amazon Associates reports.", "other_site_tag")
    blind = [s["name"] for s in sites if not s["has_gsc"]]
    if blind:
        add("warning", f"No Search Console data for {len(blind)} site{'s' if len(blind) != 1 else ''}",
            ", ".join(blind) + ". Pages there are audited but cannot be ranked by Google demand.")
    unsent = [s["name"] for s in sites if not s["submitted"]]
    if unsent:
        add("warning", f"{len(unsent)} site{'s' if len(unsent) != 1 else ''} not yet submitted to search engines", ", ".join(unsent) + ".")
    if total["first_link_very_late"]:
        add("warning", f"{total['first_link_very_late']} pages have their first Amazon link in the bottom half",
            "Most readers leave before reaching it. The fixer adds a box on pages that have visitors.", "first_link_very_late")
    return items


def build_data(cfg=None, reports: Path = Path("reports"), docs: Path = Path("docs"), state: Path = Path("data/indexnow"),
               gsc: Path = Path("data/gsc"), ga4: Path = Path("data/ga4")) -> dict:
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
            "submitted": len(sent.get("submitted", {})), "last_submission": sent.get("last_submission"),
            "submission_status": (log.get(d) or {}).get("detail", ""),
            "prev": ({k: v for k, v in site_stats(prev_by_site[d]).items() if k != "issues"} if d in prev_by_site else None),
        })
        sites.append(s)

    index = {d: i for i, d in enumerate(domains)}
    notes = []
    if (report / "summary.md").exists():
        notes.append({"slug": "full-report", "title": f"Full audit report, {report.name}", "html": markdown((report / "summary.md").read_text())})
    for n in sorted(docs.glob("*.md")) if docs.exists() else []:
        text = n.read_text()
        notes.append({"slug": n.stem, "title": text.splitlines()[0].lstrip("# ").strip() or n.stem, "html": markdown(text)})

    codes = sorted({c for r in rows for c in (r.get("issues") or "").split()} | set(ISSUE_TEXT))
    return {
        "generated": report.name, "previous": previous.name if previous else None,
        "repository": repository_slug(cfg),
        "auto_fix": list(getattr(cfg, "auto_fix", []) or []),
        "sites": sites, "cols": COLS, "pages": [_page_row(r, index) for r in rows],
        "issues": {
            c: {
                "label": ISSUE_TEXT.get(c, c.replace("_", " ")), "severity": SEVERITY.get(c, "info"), "action": ACTION.get(c, ""),
                "group": "money" if c in MONEY else ("indexing" if c in INDEXATION else "search"),
            } for c in codes
        },
        "attention": attention(sites, rows),
        "fixes": [r for r in _csv(report / "fix-log.csv") if r.get("status") in ("fixed", "saved_but_live_page_unchanged")],
        "submissions": [{**r, "total": sites[index[r["site"]]]["submitted"]} for r in _csv(report / "indexnow-log.csv") if r["site"] in index],
        "notes": notes,
    }


def build(out: Path, cfg=None, reports: Path = Path("reports"), docs: Path = Path("docs"), state: Path = Path("data/indexnow"),
          gsc: Path = Path("data/gsc"), ga4: Path = Path("data/ga4"), mirrors: list[Path] | None = None) -> Path:
    data = build_data(cfg, reports, docs, state, gsc, ga4)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for asset in sorted(ASSETS.iterdir()):
        if asset.is_file():
            shutil.copy(asset, out / asset.name)
    (out / "data.json").write_text(json.dumps(data, separators=(",", ":")))
    report = report_dirs(reports)[-1]
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
