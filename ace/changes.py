"""Compare this report with the previous one, so each run shows what got fixed and what broke."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .score import Row

# Checks that existed in engine 0.1 reports, which did not record their own check list.
V01_CHECKS = [
    "no_amazon_links", "first_link_very_late", "first_link_late", "untagged_link", "foreign_tag",
    "other_site_tag", "short_link", "missing_rel_sponsored", "no_disclosure", "search_links_only",
    "cloaked_links", "low_serp_ctr", "no_meta_description", "noindex", "canonical_elsewhere",
]
TRACKED = [
    "no_amazon_links", "first_link_very_late", "untagged_link", "other_site_tag", "no_disclosure",
    "search_links_only", "thin_content", "near_duplicate",
]


def previous_report(out: Path) -> Path | None:
    """The newest report folder older than `out` that has a pages.csv."""
    if not out.parent.exists():
        return None
    older = sorted(d for d in out.parent.iterdir() if d.is_dir() and d.name < out.name and (d / "pages.csv").exists())
    return older[-1] if older else None


def _checks(report: Path) -> set[str]:
    meta = report / "meta.json"
    return set(json.loads(meta.read_text())["checks"]) if meta.exists() else set(V01_CHECKS)


def section(prev: Path, rows: list[Row], current_checks: list[str], labels: dict[str, str]) -> list[str]:
    """Markdown lines describing what changed since `prev`. Only checks both reports ran are compared."""
    comparable = _checks(prev) & set(current_checks)
    before_issues: dict[str, Counter] = {}
    before_links: dict[str, int] = {}
    with (prev / "pages.csv").open() as f:
        for r in csv.DictReader(f):
            before_issues.setdefault(r["site"], Counter()).update(r["issues"].split())
            before_links[r["url"]] = int(r["amazon_links"] or 0)

    lines = [f"## Changes since {prev.name}", ""]
    table = []
    for site in dict.fromkeys(r.site.domain for r in rows):
        now = Counter(i for r in rows if r.site.domain == site for i in r.issues)
        was = before_issues.get(site, Counter())
        for code in TRACKED:
            if code in comparable and now[code] != was[code]:
                delta = now[code] - was[code]
                table.append(f"| {site} | {labels.get(code, code)} | {was[code]} | {now[code]} | {delta:+d} |")
    if table:
        lines += ["| Site | Check | Before | Now | Change |", "|---|---|---|---|---|"] + table
    else:
        lines.append("No change in the tracked checks.")
    lines.append("")

    lost = [r.page.url for r in rows if r.page.status == 200 and before_links.get(r.page.url, 0) > 0 and not r.page.content_links]
    if lost:
        lines += ["**Pages that had Amazon links before and have none now:**", ""] + [f"- {u}" for u in lost[:40]] + [""]
    skipped = [labels.get(c, c) for c in TRACKED if c not in comparable]
    if skipped:
        lines += [f"Not compared (new checks the earlier report did not run): {', '.join(skipped)}.", ""]
    return lines
