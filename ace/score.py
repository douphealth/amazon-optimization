"""Turn audit results + Search Console data into issues and a ranked work queue.

The ranking is a transparent heuristic, not a forecast:

    score = reachable_clicks x monetization_gap x value_weight

reachable_clicks  the larger of the page's real Google clicks and what its impressions would
                  earn at a typical click-through rate for its position (EXPECTED_CTR).
monetization_gap  how badly the page wastes those visitors (GAP_* below).
value_weight      earnings per Amazon click for the site's tracking ID, relative to the
                  portfolio average, when an Associates report is present. Otherwise 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config, Site, norm_url
from .data import GscRow, TagStats
from .page import Page

# Approximate organic click-through rate by Google position. An assumption taken from public
# CTR studies; real rates vary by query. Tune here if your Search Console data disagrees.
EXPECTED_CTR = {1: 0.28, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.07, 6: 0.05, 7: 0.04, 8: 0.03, 9: 0.025, 10: 0.025}
CTR_BEYOND_10 = 0.008

GAP_NO_LINKS = 1.0      # visitors, but no Amazon link in the article
GAP_VERY_LATE = 0.7     # first link in the bottom half
GAP_LATE = 0.4          # first link 30-50% down
GAP_OK = 0.1            # first link in the top 30%
LATE, VERY_LATE = 0.30, 0.50


def expected_ctr(position: float) -> float:
    if position <= 0:
        return 0.0
    return EXPECTED_CTR.get(round(position), CTR_BEYOND_10)


@dataclass
class Row:
    site: Site
    page: Page
    gsc: GscRow | None
    issues: list[str] = field(default_factory=list)
    gap: float = 0.0
    reachable_clicks: float = 0.0
    missed_serp_clicks: float = 0.0
    score: float = 0.0


def page_issues(page: Page, site: Site, cfg: Config) -> tuple[list[str], float]:
    """Return (issue codes, monetization gap) for one page."""
    issues: list[str] = []
    if page.error or page.status != 200:
        return [f"http_{page.status or 'error'}"], 0.0
    if page.noindex:
        issues.append("noindex")
    if page.canonical and norm_url(page.canonical) != norm_url(page.url):
        issues.append("canonical_elsewhere")
    if not page.meta_description:
        issues.append("no_meta_description")

    links = page.content_links
    depth = page.first_link_depth
    if not links:
        issues.append("no_amazon_links")
        gap = GAP_NO_LINKS
    elif depth is not None and depth >= VERY_LATE:
        issues.append("first_link_very_late")
        gap = GAP_VERY_LATE
    elif depth is not None and depth >= LATE:
        issues.append("first_link_late")
        gap = GAP_LATE
    else:
        gap = GAP_OK

    tagged = [l for l in page.links if l.kind != "short"]
    if any(not l.tag for l in tagged):
        issues.append("untagged_link")
    prefix = cfg.account_tag_prefix
    if any(l.tag and prefix and not l.tag.startswith(prefix) for l in tagged):
        issues.append("foreign_tag")
    if site.tags and any(l.tag and l.tag.startswith(prefix) and l.tag not in site.tags for l in tagged):
        issues.append("other_site_tag")
    if any(l.kind == "short" for l in page.links):
        issues.append("short_link")
    if any(not l.rel_ok for l in page.links):
        issues.append("missing_rel_sponsored")
    if page.links and not page.disclosure:
        issues.append("no_disclosure")
    if links and all(l.kind == "search" for l in links):
        issues.append("search_links_only")
    if page.cloaked_links:
        issues.append("cloaked_links")
    return issues, gap


def build_rows(
    cfg: Config,
    pages_by_site: dict[str, list[Page]],
    gsc_by_site: dict[str, dict[str, GscRow]],
    tag_stats: dict[str, TagStats],
) -> list[Row]:
    epcs = {t: s.epc for t, s in tag_stats.items() if s.epc}
    avg_epc = sum(epcs.values()) / len(epcs) if epcs else None
    rows: list[Row] = []
    for site in cfg.sites:
        site_epcs = [epcs[t] for t in site.tags if t in epcs]
        weight = (sum(site_epcs) / len(site_epcs)) / avg_epc if site_epcs and avg_epc else 1.0
        gsc = gsc_by_site.get(site.domain, {})
        for page in pages_by_site.get(site.domain, []):
            row = Row(site=site, page=page, gsc=gsc.get(norm_url(page.url)))
            row.issues, row.gap = page_issues(page, site, cfg)
            if row.gsc and row.gsc.impressions:
                g = row.gsc
                exp = expected_ctr(g.position)
                row.reachable_clicks = max(g.clicks, g.impressions * exp)
                row.missed_serp_clicks = max(0.0, g.impressions * exp - g.clicks)
                if g.position <= 12 and g.impressions >= 100 and g.clicks < 0.5 * g.impressions * exp:
                    row.issues.append("low_serp_ctr")
                row.score = round(row.reachable_clicks * row.gap * weight, 2)
            rows.append(row)
    return rows
