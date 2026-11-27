"""Bing Webmaster Tools data through its API. Bing (and Yahoo, DuckDuckGo and Ecosia, which use
Bing's index) send most of the organic visits on several of these sites, so this is first-class
data, not an extra.

Key: Bing Webmaster Tools > Settings > API access > API key, in the BING_API_KEY environment
variable (a GitHub Actions secret for the weekly run). Never commit it.

Files written per site, under data/bing/<domain>/:

  daily.csv          date, clicks, impressions           every day Bing reports (complete site totals)
  pages.csv          page, clicks, impressions, position the last `weeks` weekly buckets
  page_queries.csv   page, query, clicks, impressions, position   top queries per page
  queries.csv        query, clicks, impressions, position         the site's top queries
  crawl.csv          date, crawled_pages, in_index, code_2xx, code_4xx, code_5xx, crawl_errors, ...
  crawl_issues.csv   url, http_code, issues, in_links    URLs Bing had trouble crawling
  meta.json          site_url, start, end, weeks, pulled, totals and notes

Bing reports pages and queries per week and leaves out low-volume rows, so pages.csv covers part of
the site's clicks (the share is recorded in meta.json). Site totals come from daily.csv, which is
complete. Bing gives an average impression position but no click position.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import norm_url

API = "https://ssl.bing.com/webmaster/api.svc/json/"
WEEKS = 4
QUERIES_PER_PAGE = 10
MAX_PAGE_QUERY_CALLS = 40    # per site and run; pages with the most impressions first
PAUSE = 1.0                  # seconds between calls: Bing throttles bursts ("ThrottleHost"/"ThrottleUser")
THROTTLE_WAITS = (30, 60, 120, 240)

# Bing's CrawlIssues flags (Bing Webmaster API, CrawlIssues enumeration).
CRAWL_ISSUES = {
    1: "redirect_301", 2: "redirect_302", 4: "4xx", 8: "5xx", 16: "blocked_by_robots", 32: "malware",
    64: "important_url_blocked_by_robots", 128: "dns_error", 256: "timeout",
}
# Issues that mean a page could not be read, as opposed to a redirect Bing simply followed.
CRAWL_ERRORS = {"4xx", "5xx", "blocked_by_robots", "important_url_blocked_by_robots", "dns_error", "timeout", "malware"}


def api_key() -> str:
    return os.environ.get("BING_API_KEY", "").strip()


def available() -> bool:
    return bool(api_key())


class Throttled(RuntimeError):
    """Bing kept refusing calls for being too frequent."""


class Client:
    def __init__(self, key: str | None = None, session: requests.Session | None = None, pause: float = PAUSE,
                 waits: tuple = THROTTLE_WAITS, sleep=time.sleep):
        self.key = key or api_key()
        if not self.key:
            raise SystemExit("BING_API_KEY is not set. See ace/bing.py.")
        self.session = session or requests.Session()
        self.pause, self.waits, self.sleep = pause, waits, sleep

    def get(self, method: str, patient: bool = True, **params):
        """Call one API method. Bing answers throttling with HTTP 400 "ThrottleHost"/"ThrottleUser";
        a patient call waits and retries, an impatient one raises Throttled at once."""
        last, throttled = None, False
        waits = list(self.waits if patient else ())
        for attempt in range(len(waits) + 2):
            try:
                resp = self.session.get(API + method, params={"apikey": self.key, **params}, timeout=90)
            except requests.RequestException as exc:
                last, throttled = str(exc), False
            else:
                if self.pause:
                    self.sleep(self.pause)
                if resp.ok:
                    return resp.json().get("d")
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                throttled = "Throttle" in resp.text or resp.status_code == 429
                if not throttled and resp.status_code < 500:
                    break
            if throttled and waits:
                self.sleep(waits.pop(0))
            elif throttled:
                break
            elif attempt < 2:
                self.sleep(3 * (attempt + 1))
            else:
                break
        message = f"Bing {method} failed: {(last or '').replace(self.key, '<key>')}"
        raise Throttled(message) if throttled else RuntimeError(message)


def bing_date(value: str) -> date:
    """Bing's "/Date(1763596800000)/" (milliseconds since 1970, UTC) as a date."""
    ms = int(re.search(r"-?\d+", value).group())
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date()


def resolve_site(site, user_sites: list[str]) -> str | None:
    """The Bing site URL for a site: the configured one, or the verified site with the same host."""
    if getattr(site, "bing_site", ""):
        return site.bing_site
    host = site.domain.lower().removeprefix("www.")
    for url in user_sites:
        if norm_url(url).split("/")[0] == host:
            return url
    return None


def aggregate(rows: list[dict], key: str, buckets: set[date]) -> dict[str, dict]:
    """Sum weekly rows per `key` (Query field) over the chosen buckets. Position is the
    impression-weighted average of Bing's AvgImpressionPosition."""
    out: dict[str, dict] = defaultdict(lambda: {"clicks": 0, "impressions": 0, "_pos": 0.0})
    for r in rows:
        if bing_date(r["Date"]) not in buckets:
            continue
        e = out[r[key]]
        e["clicks"] += r.get("Clicks", 0)
        e["impressions"] += r.get("Impressions", 0)
        pos = r.get("AvgImpressionPosition", -1)
        if pos and pos > 0:
            e["_pos"] += pos * r.get("Impressions", 0)
    for e in out.values():
        e["position"] = round(e.pop("_pos") / e["impressions"], 1) if e["impressions"] else ""
    return dict(out)


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def decode_issues(flags: int) -> list[str]:
    return [name for bit, name in CRAWL_ISSUES.items() if flags & bit]


def pull_site(client: Client, site, site_url: str, root: Path, weeks: int = WEEKS, today: date | None = None, log=print) -> dict:
    today = today or date.today()
    folder = root / site.domain

    daily = sorted(({"date": bing_date(r["Date"]).isoformat(), "clicks": r["Clicks"], "impressions": r["Impressions"]}
                    for r in client.get("GetRankAndTrafficStats", siteUrl=site_url) or []), key=lambda r: r["date"])
    _write(folder / "daily.csv", ["date", "clicks", "impressions"], daily)

    page_rows = client.get("GetPageStats", siteUrl=site_url) or []
    query_rows = client.get("GetQueryStats", siteUrl=site_url) or []
    buckets = sorted({bing_date(r["Date"]) for r in page_rows + query_rows})
    window = set(buckets[-weeks:])
    pages = aggregate(page_rows, "Query", window)
    queries = aggregate(query_rows, "Query", window)
    page_list = sorted(({"page": k, **v} for k, v in pages.items()), key=lambda r: (-r["clicks"], -r["impressions"]))
    _write(folder / "pages.csv", ["page", "clicks", "impressions", "position"], page_list)
    _write(folder / "queries.csv", ["query", "clicks", "impressions", "position"],
           sorted(({"query": k, **v} for k, v in queries.items()), key=lambda r: (-r["clicks"], -r["impressions"])))

    # Top queries for each page Bing reported, busiest pages first.
    targets = [p["page"] for p in page_list if p["impressions"]][:MAX_PAGE_QUERY_CALLS]

    # Optional extra: one call per page, made one at a time. On throttling, keep what was fetched.
    pq, done = [], 0
    for url in targets:
        try:
            rows = client.get("GetPageQueryStats", patient=False, siteUrl=site_url, page=url) or []
        except Throttled:
            log(f"[{site.domain}] Bing throttled per-page queries after {done} pages; the rest next run")
            break
        except RuntimeError as exc:
            log(f"[{site.domain}] {exc}")
            continue
        done += 1
        agg = aggregate(rows, "Query", window)
        pq += sorted(({"page": url, "query": q, **v} for q, v in agg.items() if v["impressions"]),
                     key=lambda r: (-r["clicks"], -r["impressions"]))[:QUERIES_PER_PAGE]
    _write(folder / "page_queries.csv", ["page", "query", "clicks", "impressions", "position"], pq)

    crawl = sorted(({
        "date": bing_date(r["Date"]).isoformat(), "crawled_pages": r.get("CrawledPages", 0), "in_index": r.get("InIndex", 0),
        "code_2xx": r.get("Code2xx", 0), "code_301": r.get("Code301", 0), "code_302": r.get("Code302", 0), "code_4xx": r.get("Code4xx", 0),
        "code_5xx": r.get("Code5xx", 0), "crawl_errors": r.get("CrawlErrors", 0), "blocked_by_robots": r.get("BlockedByRobotsTxt", 0),
        "in_links": r.get("InLinks", 0),
    } for r in client.get("GetCrawlStats", siteUrl=site_url) or []), key=lambda r: r["date"])
    _write(folder / "crawl.csv", ["date", "crawled_pages", "in_index", "code_2xx", "code_301", "code_302", "code_4xx", "code_5xx",
                                  "crawl_errors", "blocked_by_robots", "in_links"], crawl)

    issues = [{"url": r["Url"], "http_code": r.get("HttpCode", ""), "issues": " ".join(decode_issues(r.get("Issues", 0))), "in_links": r.get("InLinks", 0)}
              for r in client.get("GetCrawlIssues", siteUrl=site_url) or []]
    _write(folder / "crawl_issues.csv", ["url", "http_code", "issues", "in_links"], issues)

    # A weekly bucket dated D covers the seven days D-7 to D-1 (Friday to Thursday, labelled with the
    # following Friday). Checked against the complete daily totals on all nine sites: it is the only
    # offset under which a week's page clicks never exceed the site's clicks for that week.
    first, last = (min(window) - timedelta(days=7), max(window) - timedelta(days=1)) if window else (None, None)
    days_in_window = [d for d in daily if first and first.isoformat() <= d["date"] <= last.isoformat()]
    site_clicks = sum(d["clicks"] for d in days_in_window)
    page_clicks = sum(p["clicks"] for p in page_list)
    meta = {
        "site_url": site_url, "pulled": today.isoformat(), "weeks": len(window),
        "start": first.isoformat() if first else None, "end": last.isoformat() if last else None,
        "daily_start": daily[0]["date"] if daily else None, "daily_end": daily[-1]["date"] if daily else None,
        "site_clicks_in_window": site_clicks, "page_clicks_in_window": page_clicks,
        "page_share_of_clicks": round(page_clicks / site_clicks, 2) if site_clicks else None,
        "note": "Bing Webmaster API. Pages and queries are weekly and omit low-volume rows; daily totals are complete.",
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=1))
    errors = sum(1 for i in issues if set(i["issues"].split()) & CRAWL_ERRORS)
    log(f"[{site.domain}] Bing: {len(page_list)} pages, {page_clicks} of {site_clicks} clicks attributed to pages "
        f"({meta['start']} to {meta['end']}), {len(pq)} page queries, {len(issues)} crawl-issue URLs ({errors} errors)")
    return meta


def pull(sites, root: str | Path = "data/bing", client: Client | None = None, weeks: int = WEEKS, today: date | None = None, log=print) -> dict[str, dict]:
    client = client or Client()
    try:
        user_sites = [s["Url"] for s in client.get("GetUserSites") or [] if s.get("IsVerified")]
    except RuntimeError as exc:
        log(f"Bing skipped: {exc}")
        return {}
    out = {}
    for site in sites:
        site_url = resolve_site(site, user_sites)
        if not site_url:
            log(f"[{site.domain}] not a verified site in this Bing Webmaster account")
            continue
        try:
            out[site.domain] = pull_site(client, site, site_url, Path(root), weeks=weeks, today=today, log=log)
        except Exception as exc:  # one site failing must not stop the rest
            log(f"[{site.domain}] Bing pull failed: {exc}")
    return out


def load_pages(domain: str, root: str | Path = "data/bing") -> dict[str, dict]:
    path = Path(root) / domain / "pages.csv"
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {norm_url(r["page"]): r for r in csv.DictReader(f)}


def load_crawl_errors(domain: str, root: str | Path = "data/bing") -> dict[str, dict]:
    """{normalised url: row} for URLs Bing could not crawl (redirects it followed are left out)."""
    path = Path(root) / domain / "crawl_issues.csv"
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {norm_url(r["url"]): r for r in csv.DictReader(f) if set(r["issues"].split()) & CRAWL_ERRORS}
