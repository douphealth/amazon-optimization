"""Search Console data through the official API: every page, its top queries, the daily trend,
and Google's own verdict on whether each page is indexed (URL Inspection).

Credentials and access: see ace/gcp.py. Files written per site, under data/gsc/<domain>/:

  pages.csv     page, clicks, impressions, position        last `days` days, every page
  queries.csv   page, query, clicks, impressions, position top queries per page
  daily.csv     date, clicks, impressions, position        last 90 days, whole site
  sitemaps.csv  path, last_submitted, last_downloaded, ...  the sitemaps Google holds for the property
  meta.json     property, start, end, pulled, note
  index.csv     url, inspected, verdict, coverage, ...     one row per inspected page (URL Inspection)

The API has no row cap that matters here (25,000 rows per request, paged). URL Inspection allows
2,000 inspections per property per day; `inspect` stays under that and refreshes the oldest first.
"""
from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import gcp
from .config import norm_url

API = "https://www.googleapis.com/webmasters/v3"
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
SCOPE = gcp.SEARCH_CONSOLE
PAGE_SIZE = 25000
LAG_DAYS = 3          # Search Console's final data trails by two to three days
TREND_DAYS = 90
QUERIES_PER_PAGE = 10
INSPECT_DAILY_CAP = 1900   # stay under the 2,000-per-property daily quota
INSPECT_REFRESH_DAYS = 7
INSPECT_WORKERS = 12       # each call takes ~6 s; Google allows 600 per minute per property
INSPECT_SAVE_EVERY = 100   # write results as they come, so an interrupted run keeps its work
INDEX_FIELDS = ["url", "inspected", "verdict", "coverage", "indexing_state", "robots_txt", "page_fetch",
                "google_canonical", "user_canonical", "last_crawl", "crawled_as"]


def authed_session():
    return gcp.session(SCOPE)


def list_properties(session) -> list[str]:
    resp = session.get(f"{API}/sites", timeout=60)
    resp.raise_for_status()
    return [e["siteUrl"] for e in resp.json().get("siteEntry", []) if e.get("permissionLevel") != "siteUnverifiedUser"]


def resolve_property(site, available: list[str]) -> str | None:
    """The Search Console property to use for a site: the configured one if the account can see it,
    else the domain property, else a URL-prefix property for the site's address."""
    host = site.domain.lower().removeprefix("www.")
    candidates = [site.gsc_property, f"sc-domain:{host}", f"https://{host}/", f"https://www.{host}/", f"http://{host}/", f"http://www.{host}/"]
    return next((c for c in candidates if c and c in available), None)


def _query(session, prop: str, body: dict) -> list[dict]:
    url = f"{API}/sites/{quote(prop, safe='')}/searchAnalytics/query"
    rows, offset = [], 0
    while True:
        resp = session.post(url, json={**body, "rowLimit": PAGE_SIZE, "startRow": offset}, timeout=120)
        resp.raise_for_status()
        batch = resp.json().get("rows", [])
        rows += batch
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def query_pages(session, gsc_property: str, start: date, end: date) -> list[dict]:
    """[{page, clicks, impressions, position}] for every page with impressions in the range."""
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": ["page"], "type": "web"}
    rows = [{"page": r["keys"][0], "clicks": r["clicks"], "impressions": r["impressions"], "position": round(r["position"], 2)}
            for r in _query(session, gsc_property, body)]
    return sorted(rows, key=lambda r: (-r["clicks"], -r["impressions"], r["page"]))


def query_page_queries(session, gsc_property: str, start: date, end: date, per_page: int = QUERIES_PER_PAGE) -> list[dict]:
    """Top queries per page, by impressions. Google withholds rare queries, so these add up to less
    than the page totals."""
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": ["page", "query"], "type": "web"}
    by_page: dict[str, list[dict]] = {}
    for r in _query(session, gsc_property, body):
        by_page.setdefault(r["keys"][0], []).append(
            {"page": r["keys"][0], "query": r["keys"][1], "clicks": r["clicks"], "impressions": r["impressions"], "position": round(r["position"], 2)})
    out = []
    for rows in by_page.values():
        out += sorted(rows, key=lambda r: (-r["clicks"], -r["impressions"]))[:per_page]
    return out


def query_daily(session, gsc_property: str, start: date, end: date) -> list[dict]:
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": ["date"], "type": "web"}
    return sorted(({"date": r["keys"][0], "clicks": r["clicks"], "impressions": r["impressions"], "position": round(r["position"], 2)}
                   for r in _query(session, gsc_property, body)), key=lambda r: r["date"])


def list_sitemaps(session, prop: str) -> list[dict]:
    resp = session.get(f"{API}/sites/{quote(prop, safe='')}/sitemaps", timeout=60)
    resp.raise_for_status()
    out = []
    for m in resp.json().get("sitemap", []):
        web = sum(int(c.get("submitted", 0) or 0) for c in m.get("contents", []) if c.get("type") == "web")
        out.append({"path": m.get("path", ""), "last_submitted": (m.get("lastSubmitted") or "")[:10],
                    "last_downloaded": (m.get("lastDownloaded") or "")[:10], "pending": m.get("isPending", False),
                    "errors": int(m.get("errors", 0) or 0), "warnings": int(m.get("warnings", 0) or 0), "web_urls": web})
    return out


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def pull(sites, days: int = 28, root: str | Path = "data/gsc", session=None, today: date | None = None, log=print) -> dict[str, str]:
    """Write pages, queries, daily trend and meta for every site. Returns {domain: property used}."""
    session = session or authed_session()
    today = today or date.today()
    end = today - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=days - 1)
    try:
        available = list_properties(session)
    except Exception as exc:
        log(f"Search Console skipped: could not list properties ({exc})")
        return {}
    used = {}
    for site in sites:
        prop = resolve_property(site, available)
        if not prop:
            log(f"[{site.domain}] no Search Console property this account can read (add the service account as a user)")
            continue
        if site.gsc_property and prop != site.gsc_property:
            log(f"[{site.domain}] sites.yaml names {site.gsc_property}, which this account cannot see; using {prop}")
        try:
            pages = query_pages(session, prop, start, end)
            queries = query_page_queries(session, prop, start, end)
            daily = query_daily(session, prop, end - timedelta(days=TREND_DAYS - 1), end)
            sitemaps = list_sitemaps(session, prop)
        except Exception as exc:  # one failing property must not stop the rest
            log(f"[{site.domain}] Search Console pull failed: {exc}")
            continue
        folder = Path(root) / site.domain
        _write(folder / "pages.csv", ["page", "clicks", "impressions", "position"], pages)
        _write(folder / "queries.csv", ["page", "query", "clicks", "impressions", "position"], queries)
        _write(folder / "daily.csv", ["date", "clicks", "impressions", "position"], daily)
        _write(folder / "sitemaps.csv", ["path", "last_submitted", "last_downloaded", "pending", "errors", "warnings", "web_urls"], sitemaps)
        (folder / "meta.json").write_text(json.dumps({
            "property": prop, "start": start.isoformat(), "end": end.isoformat(), "pulled": today.isoformat(),
            "note": "Search Console API, every page with impressions",
        }, indent=1))
        used[site.domain] = prop
        log(f"[{site.domain}] Search Console: {len(pages)} pages, {int(sum(p['clicks'] for p in pages))} clicks, "
            f"{int(sum(p['impressions'] for p in pages))} impressions ({start} to {end}) from {prop}")
    return used


# ---------- URL Inspection ----------

def _inspection_row(url: str, result: dict, today: date) -> dict:
    s = result.get("inspectionResult", {}).get("indexStatusResult", {})
    return {
        "url": url, "inspected": today.isoformat(), "verdict": s.get("verdict", ""), "coverage": s.get("coverageState", ""),
        "indexing_state": s.get("indexingState", ""), "robots_txt": s.get("robotsTxtState", ""), "page_fetch": s.get("pageFetchState", ""),
        "google_canonical": s.get("googleCanonical", ""), "user_canonical": s.get("userCanonical", ""),
        "last_crawl": (s.get("lastCrawlTime") or "")[:10], "crawled_as": s.get("crawledAs", ""),
    }


def load_index(domain: str, root: str | Path = "data/gsc") -> dict[str, dict]:
    """{normalised url: inspection row} from data/gsc/<domain>/index.csv."""
    path = Path(root) / domain / "index.csv"
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {norm_url(r["url"]): r for r in csv.DictReader(f)}


def inspect(site_urls, root: str | Path = "data/gsc", session_factory=None, today: date | None = None,
            refresh_days: int = INSPECT_REFRESH_DAYS, cap: int = INSPECT_DAILY_CAP, workers: int = INSPECT_WORKERS,
            log=print) -> dict[str, int]:
    """Ask Google whether each page is indexed. `site_urls` is a list of (Site, URLs), most important URLs first.

    Pages inspected within `refresh_days` are skipped, so repeated runs spread the daily quota.
    Results are merged into data/gsc/<domain>/index.csv. Returns {domain: pages inspected now}."""
    today = today or date.today()
    pool = gcp.PerThread(SCOPE, factory=session_factory) if session_factory or gcp.available() else None
    if pool is None:
        raise SystemExit("No Google service account: set GSC_SERVICE_ACCOUNT_JSON (see ace/gcp.py).")
    try:
        available = list_properties(pool.get())
    except Exception as exc:
        log(f"URL inspection skipped: could not list Search Console properties ({exc})")
        return {}
    done: dict[str, int] = {}
    for site, urls in (site_urls.items() if isinstance(site_urls, dict) else site_urls):
        try:
            done.update(_inspect_site(site, urls, available, root, pool, today, refresh_days, cap, workers, log))
        except Exception as exc:  # one site failing must not stop the others
            log(f"[{site.domain}] URL inspection failed: {exc}")
    return done


def _inspect_site(site, urls, available, root, pool, today, refresh_days, cap, workers, log) -> dict[str, int]:
    """Inspect one site's URLs; see `inspect`."""
    done: dict[str, int] = {}
    prop = resolve_property(site, available)
    if not prop:
        log(f"[{site.domain}] URL inspection skipped: no Search Console property")
        return done
    known = load_index(site.domain, root)

    def fresh(url: str) -> bool:
        row = known.get(norm_url(url))
        if not row or row.get("verdict") == "ERROR":
            return False
        try:
            return (today - date.fromisoformat(row.get("inspected", ""))).days < refresh_days
        except ValueError:
            return False

    todo = [u for u in dict.fromkeys(urls) if not fresh(u)]
    # a URL-prefix property only accepts URLs under its own prefix
    if not prop.startswith("sc-domain:"):
        todo = [u for u in todo if u.startswith(prop) or urlsplit(u).netloc == urlsplit(prop).netloc]
    todo = todo[:cap]
    if not todo:
        log(f"[{site.domain}] URL inspection: all {len(known)} pages checked within {refresh_days} days")
        return done
    stop = {"quota": False}

    def one(url):
        if stop["quota"]:
            return None
        for attempt in range(3):
            try:
                resp = pool.get().post(INSPECT, json={"inspectionUrl": url, "siteUrl": prop}, timeout=90)
            except Exception:  # timeouts, dropped connections, token refresh: retry, then skip this URL
                if attempt < 2:
                    continue
                return None
            if resp.status_code == 429:
                stop["quota"] = True
                return None
            if resp.status_code >= 500 and attempt < 2:
                continue
            if not resp.ok:
                return {"url": url, "inspected": today.isoformat(), "verdict": "ERROR", "coverage": f"HTTP {resp.status_code}"}
            try:
                return _inspection_row(url, resp.json(), today)
            except ValueError:
                return None
        return None

    results = []
    path = Path(root) / site.domain / "index.csv"
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, todo):
            if not r:
                continue
            results.append(r)
            known[norm_url(r["url"])] = r
            if len(results) % INSPECT_SAVE_EVERY == 0:
                _write(path, INDEX_FIELDS, sorted(known.values(), key=lambda x: x["url"]))
                log(f"[{site.domain}] URL inspection: {len(results)} of {len(todo)} checked")
    _write(path, INDEX_FIELDS, sorted(known.values(), key=lambda r: r["url"]))
    done[site.domain] = len(results)
    indexed = sum(1 for r in known.values() if r.get("verdict") == "PASS")
    log(f"[{site.domain}] URL inspection: {len(results)} pages checked now; {indexed} of {len(known)} known pages are in Google's index"
        + (" (daily quota reached, the rest next run)" if stop["quota"] else ""))
    return done
