"""Write the audit to disk: audit.json (reloadable), CSVs for spreadsheets, summary.md for humans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import median

from .config import Config
from .data import TagStats
from .page import Link, Page
from .score import Row

ISSUE_TEXT = {
    "no_amazon_links": "no Amazon link in the article",
    "first_link_very_late": "first Amazon link is in the bottom half",
    "first_link_late": "first Amazon link is 30-50% down",
    "untagged_link": "Amazon link with no tracking tag (earns nothing)",
    "foreign_tag": "Amazon link with someone else's tag",
    "other_site_tag": "uses a tracking ID that is not this site's (clicks cannot be attributed to it)",
    "short_link": "amzn.to short link (tag cannot be checked)",
    "missing_rel_sponsored": "Amazon link without rel=sponsored/nofollow",
    "no_disclosure": "Amazon links but no \"As an Amazon Associate\" disclosure",
    "search_links_only": "only Amazon search links, no product links",
    "cloaked_links": "redirect-style links (/go/, /recommends/)",
    "low_serp_ctr": "Google shows it but few people click (title/description)",
    "no_meta_description": "no meta description",
    "noindex": "noindex",
    "canonical_elsewhere": "canonical points to another URL",
}


def save_audit(out: Path, pages_by_site: dict[str, list[Page]], sitemaps: dict[str, dict[str, list[str]]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "pages": {d: [asdict(p) for p in pages] for d, pages in pages_by_site.items()},
        "sitemaps": sitemaps,
    }
    (out / "audit.json").write_text(json.dumps(payload))


def load_audit(out: Path) -> tuple[dict[str, list[Page]], dict[str, dict[str, list[str]]]]:
    payload = json.loads((out / "audit.json").read_text())
    pages_by_site = {}
    for domain, pages in payload["pages"].items():
        pages_by_site[domain] = [
            Page(**{**p, "links": [Link(**l) for l in p["links"]]}) for p in pages
        ]
    return pages_by_site, payload["sitemaps"]


def _pct(value: float | None) -> str:
    return "" if value is None else f"{value:.0%}"


def write_csvs(out: Path, rows: list[Row]) -> None:
    with (out / "pages.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "site", "url", "status", "words", "commercial_intent", "amazon_links", "product_links",
            "search_links", "short_links", "first_link_depth", "tags", "disclosure", "gsc_clicks",
            "gsc_impressions", "gsc_position", "score", "issues",
        ])
        for r in rows:
            p, links = r.page, r.page.content_links
            w.writerow([
                r.site.domain, p.url, p.status, p.words, int(p.commercial), len(links),
                sum(l.kind == "product" for l in links), sum(l.kind == "search" for l in links),
                sum(l.kind == "short" for l in p.links), p.first_link_depth if links else "",
                " ".join(sorted({l.tag for l in p.links if l.tag})), int(p.disclosure),
                r.gsc.clicks if r.gsc else "", r.gsc.impressions if r.gsc else "",
                round(r.gsc.position, 1) if r.gsc else "", r.score, " ".join(r.issues),
            ])
    with (out / "links.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "page", "href", "kind", "tag", "asin", "rel_ok", "in_site_chrome", "name"])
        for r in rows:
            for l in r.page.links:
                w.writerow([r.site.domain, r.page.url, l.href, l.kind, l.tag, l.asin, int(l.rel_ok), int(l.in_chrome), l.name])


def _site_block(cfg: Config, rows: list[Row], sitemaps: dict[str, dict[str, list[str]]], gsc_meta: dict[str, dict]) -> list[str]:
    lines = [
        "| Site | Pages crawled | Loaded OK | Pages with Amazon links | Amazon links | Typical first-link depth | Pages Google showed | Google clicks |",
        "|---|---|---|---|---|---|---|---|",
    ]
    details = []
    for site in cfg.sites:
        rs = [r for r in rows if r.site.domain == site.domain]
        if not rs:
            lines.append(f"| {site.name} | 0 (no sitemap found) | | | | | | |")
            continue
        ok = [r for r in rs if r.page.status == 200]
        with_links = [r for r in ok if r.page.content_links]
        depths = [r.page.first_link_depth for r in with_links if r.page.first_link_depth is not None]
        gsc_rows = [r for r in rs if r.gsc]
        has_gsc = site.domain in gsc_meta
        lines.append(
            f"| {site.name} | {len(rs)} | {len(ok)} | {len(with_links)} | "
            f"{sum(len(r.page.links) for r in ok)} | {_pct(median(depths)) if depths else 'n/a'} | "
            f"{len(gsc_rows) if has_gsc else 'no data'} | "
            f"{int(sum(r.gsc.clicks for r in gsc_rows)) if has_gsc else 'no data'} |"
        )
        counts = Counter(i for r in rs for i in r.issues)
        tags = Counter(l.tag or "(none)" for r in ok for l in r.page.links if l.kind != "short")
        dupes = sum(1 for srcs in sitemaps.get(site.domain, {}).values() if len(srcs) > 1)
        block = [f"### {site.name} ({site.domain})"]
        if tags:
            block.append("- Tracking IDs in use: " + ", ".join(f"`{t}` ({n} links)" for t, n in tags.most_common()))
        for code, n in counts.most_common():
            if code in ISSUE_TEXT:
                block.append(f"- {n} pages: {ISSUE_TEXT[code]}")
            elif code.startswith("http_"):
                block.append(f"- {n} sitemap URLs returned {code.removeprefix('http_')}")
        if dupes:
            block.append(f"- {dupes} URLs are listed in more than one sitemap")
        if ok and not any(r.page.onelink for r in ok) and with_links:
            block.append("- No OneLink script found (non-US visitors land on amazon.com)")
        if len(block) > 1:
            details.extend(block + [""])
    return lines + [""] + details


def write_summary(
    out: Path, cfg: Config, rows: list[Row], sitemaps: dict[str, dict[str, list[str]]],
    gsc_meta: dict[str, dict], tag_stats: dict[str, TagStats], top: int = 30,
) -> None:
    lines = [f"# Amazon commission audit: {out.name}", ""]
    lines += ["## Portfolio", ""] + _site_block(cfg, rows, sitemaps, gsc_meta)

    if tag_stats:
        lines += ["## Earnings per click by tracking ID (Associates report)", "",
                  "| Tracking ID | Clicks | Items | Earnings | Earnings per click |", "|---|---|---|---|---|"]
        for tag, s in sorted(tag_stats.items(), key=lambda kv: -kv[1].earnings):
            epc = f"${s.epc:.3f}" if s.epc is not None else "n/a"
            lines.append(f"| `{tag}` | {int(s.clicks)} | {int(s.items)} | ${s.earnings:.2f} | {epc} |")
        lines.append("")

    ranked = sorted((r for r in rows if r.score > 0), key=lambda r: -r.score)[:top]
    lines += ["## Work queue: pages losing the most Amazon clicks", ""]
    if ranked:
        lines += ["| # | Page | Google clicks | Impressions | Position | First link | Problem | Score |",
                  "|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(ranked, 1):
            problems = "; ".join(ISSUE_TEXT[c] for c in r.issues if c in ISSUE_TEXT) or "links are placed well"
            depth = _pct(r.page.first_link_depth) if r.page.content_links else "none"
            lines.append(
                f"| {i} | {r.page.url} | {int(r.gsc.clicks)} | {int(r.gsc.impressions)} | "
                f"{r.gsc.position:.1f} | {depth} | {problems} | {r.score} |"
            )
    else:
        lines.append("No page has Search Console data yet. Add `data/gsc/<domain>/pages.csv` (see README).")
    lines.append("")

    ctr = sorted((r for r in rows if "low_serp_ctr" in r.issues), key=lambda r: -r.missed_serp_clicks)[:15]
    if ctr:
        lines += ["## Title and description rewrites: shown on page 1 but rarely clicked", "",
                  "| Page | Impressions | Position | Clicks | Current title |", "|---|---|---|---|---|"]
        for r in ctr:
            lines.append(f"| {r.page.url} | {int(r.gsc.impressions)} | {r.gsc.position:.1f} | {int(r.gsc.clicks)} | {r.page.title} |")
        lines.append("")

    lines += ["## Data used", ""]
    for site in cfg.sites:
        meta = gsc_meta.get(site.domain)
        if meta:
            lines.append(f"- {site.domain}: Search Console {meta.get('start', '?')} to {meta.get('end', '?')} ({meta.get('note', 'full export')})")
    lines += [
        "- Sites not listed above have no Search Console file, so their pages are audited but not ranked.",
        "- Scores are a heuristic (see `ace/score.py`): expected click-through rates by position are an assumption.",
        "",
    ]
    (out / "summary.md").write_text("\n".join(lines))
