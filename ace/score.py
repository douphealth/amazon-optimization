"""Turn audit results + Search Console data into issues and a ranked work queue.

The ranking is a transparent heuristic, not a forecast:

    score = reachable_clicks x monetization_gap x value_weight

reachable_clicks  per search engine (Google, Bing), the larger of the page's real clicks and what
                  its impressions would earn at a typical click-through rate for its position
                  (EXPECTED_CTR), summed; at least the visits analytics recorded.
monetization_gap  how badly the page wastes those visitors (GAP_* below).
value_weight      earnings per Amazon click for the site's tracking ID, relative to the
                  portfolio average, when an Associates report is present. Otherwise 1.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import dupes
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
THIN_WORDS = 300
DEMAND_BING_IMPRESSIONS = 20
# URL Inspection states that describe the page as Google last fetched it. When the live page is now a
# normal indexable 200, the verdict is out of date rather than a problem with the page.
OUTDATED_IF_INDEXABLE = {
    "Excluded by \u2018noindex\u2019 tag", "Not found (404)", "Soft 404", "Page with redirect", "Server error (5xx)",
    "Blocked by robots.txt", "Blocked due to access forbidden (403)", "Blocked due to other 4xx issue",
}  # four weeks of Bing impressions that count as search demand on their own        # below this an article is unlikely to satisfy a search


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
    cluster_size: int = 0  # how many pages on the site share most of this page's text
    amazon_clicks: float = 0.0  # outbound Amazon clicks recorded by analytics
    sessions: float = 0.0       # organic visits that landed here (analytics)
    bing: GscRow | None = None  # Bing Webmaster clicks, impressions, position
    index: dict | None = None   # Google URL Inspection result (see ace/gsc.py)

    @property
    def search_clicks(self) -> float:
        return (self.gsc.clicks if self.gsc else 0.0) + (self.bing.clicks if self.bing else 0.0)

    @property
    def visits(self) -> float:
        """Best available count of real visitors: search clicks from Google and Bing, organic
        sessions recorded by analytics, or at least as many as clicked through to Amazon."""
        return max(self.search_clicks, self.sessions, self.amazon_clicks)


def page_issues(page: Page, site: Site, cfg: Config) -> tuple[list[str], float]:
    """Return (issue codes, monetization gap) for one page."""
    issues: list[str] = []
    if page.error or page.status != 200:
        return [f"http_{page.status or 'error'}"], 0.0
    if page.noindex:
        issues.append("noindex")
    if page.canonical and norm_url(page.canonical) != norm_url(page.url):
        issues.append("canonical_elsewhere")
    if page.final_url and norm_url(page.final_url) != norm_url(page.url):
        issues.append("redirects")
    if not page.meta_description:
        issues.append("no_meta_description")
    if page.words < THIN_WORDS:
        issues.append("thin_content")

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
    if page.links and not page.affiliate_notice:
        issues.append("no_disclosure")
    if links and all(l.kind == "search" for l in links):
        issues.append("search_links_only")
    if page.cloaked_links:
        issues.append("cloaked_links")
    if any(l.asin in cfg.blocked_asins for l in page.links):
        issues.append("blocked_product")
    return issues, gap


def index_issues(row: Row) -> list[str]:
    """Findings from Google's URL Inspection verdict, for pages that are meant to be indexed."""
    ix, page = row.index, row.page
    if not ix or ix.get("verdict") in ("", "ERROR") or page.noindex:
        return []
    if page.canonical and norm_url(page.canonical) != norm_url(page.url):
        return []  # the page itself points Google elsewhere; nothing to add
    if ix.get("verdict") == "PASS":
        chosen = ix.get("google_canonical", "")
        return ["google_canonical_mismatch"] if chosen and norm_url(chosen) != norm_url(page.url) else []
    if ix.get("coverage") in OUTDATED_IF_INDEXABLE:
        # Google last saw a noindex, an error or a redirect; today the page loads and is indexable.
        return ["google_verdict_outdated"]
    demand = row.visits > 0 or row.amazon_clicks > 0 or (row.bing is not None and row.bing.impressions >= DEMAND_BING_IMPRESSIONS)
    return ["demand_page_not_in_google" if demand else "not_in_google"]


def build_rows(
    cfg: Config,
    pages_by_site: dict[str, list[Page]],
    gsc_by_site: dict[str, dict[str, GscRow]],
    tag_stats: dict[str, TagStats],
    ga_by_site: dict[str, dict[str, dict]] | None = None,
    bing_by_site: dict[str, dict[str, GscRow]] | None = None,
    index_by_site: dict[str, dict[str, dict]] | None = None,
    bing_errors_by_site: dict[str, dict[str, dict]] | None = None,
) -> list[Row]:
    epcs = {t: s.epc for t, s in tag_stats.items() if s.epc}
    avg_epc = sum(epcs.values()) / len(epcs) if epcs else None
    rows: list[Row] = []
    for site in cfg.sites:
        site_epcs = [epcs[t] for t in site.tags if t in epcs]
        weight = (sum(site_epcs) / len(site_epcs)) / avg_epc if site_epcs and avg_epc else 1.0
        gsc = gsc_by_site.get(site.domain, {})
        ga = (ga_by_site or {}).get(site.domain, {})
        bing = (bing_by_site or {}).get(site.domain, {})
        index = (index_by_site or {}).get(site.domain, {})
        bing_errors = (bing_errors_by_site or {}).get(site.domain, {})
        pages = pages_by_site.get(site.domain, [])
        ok_pages = [p for p in pages if p.status == 200]
        near_dupes = dupes.clusters(ok_pages)
        titles = Counter(p.title for p in ok_pages if p.title)
        for page in pages:
            key = norm_url(page.url)
            row = Row(site=site, page=page, gsc=gsc.get(key), bing=bing.get(key), index=index.get(key))
            row.issues, row.gap = page_issues(page, site, cfg)
            row.cluster_size = near_dupes.get(page.url, 0)
            if row.cluster_size:
                row.issues.append("near_duplicate")
            if page.status == 200 and titles[page.title] > 1:
                row.issues.append("duplicate_title")
            seen = ga.get(norm_url(page.url))
            if seen:
                row.amazon_clicks, row.sessions = seen["amazon_clicks"], seen["sessions"]
                if row.amazon_clicks and page.status == 200 and page.noindex:
                    row.issues.append("earning_page_noindexed")
            for engine, code in ((row.gsc, "low_serp_ctr"), (row.bing, "low_bing_ctr")):
                if not engine or not engine.impressions:
                    continue
                exp = expected_ctr(engine.position)
                row.reachable_clicks += max(engine.clicks, engine.impressions * exp)
                row.missed_serp_clicks += max(0.0, engine.impressions * exp - engine.clicks)
                if 0 < engine.position <= 12 and engine.impressions >= 100 and engine.clicks < 0.5 * engine.impressions * exp:
                    row.issues.append(code)
            if page.status == 200:
                row.issues += index_issues(row)
                if key in bing_errors:
                    row.issues.append("bing_crawl_error")
            row.reachable_clicks = max(row.reachable_clicks, row.visits)
            row.score = round(row.reachable_clicks * row.gap * weight, 2)
            rows.append(row)
    return rows
