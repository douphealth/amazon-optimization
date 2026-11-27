"""Google Analytics 4 through the Data API, with the same service account as Search Console
(see ace/gcp.py). No third-party connector and no row cap that matters here.

Which property: each run reads the Analytics tag(s) the site's homepage actually loads (G-... IDs)
and looks them up among the properties the service account can read. A property whose tag is on the
site comes first; then the ones listed under ga4_properties in sites.yaml. The first that records
visits for the site's own hostname is used, so visits are never counted twice. When the live tag
belongs to a property the account cannot read, meta.json says so, with the tag ID to look for.

Files written per site, under data/ga4/<domain>/:

  sessions.csv        page, sessions, engaged_sessions   organic-search sessions by landing page
  amazon_clicks.csv   page, amazon_clicks                outbound clicks to Amazon, by page
  sources.csv         source, medium, channel, sessions, engaged_sessions
  daily.csv           date, sessions, engaged_sessions, organic_sessions
  meta.json           property, start, end, pulled, totals and notes

Amazon clicks are GA4's `click` events (enhanced measurement, outbound links) whose link domain is
an Amazon or amzn.to address.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, timedelta
from pathlib import Path

import requests

from . import gcp

API = "https://analyticsdata.googleapis.com/v1beta/properties/{pid}:runReport"
SCOPE = gcp.ANALYTICS
PAGE_SIZE = 100000
AMAZON_LINK = r"(^|\.)(amazon\.[a-z.]+|amzn\.(to|eu|asia))$"


ADMIN = "https://analyticsadmin.googleapis.com/v1beta"
TAG = re.compile(r"\b(G-[A-Z0-9]{6,12})\b")
GTM = re.compile(r"\b(GTM-[A-Z0-9]{4,10})\b")
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def readable_streams(session) -> dict[str, str]:
    """{measurement ID: property ID} for every web stream the service account can read."""
    out, token = {}, None
    while True:
        resp = session.get(f"{ADMIN}/accountSummaries", params={"pageSize": 200, **({"pageToken": token} if token else {})}, timeout=60)
        resp.raise_for_status()
        j = resp.json()
        for account in j.get("accountSummaries", []):
            for prop in account.get("propertySummaries", []):
                pid = prop["property"].split("/")[-1]
                streams = session.get(f"{ADMIN}/properties/{pid}/dataStreams", timeout=60)
                for s in streams.json().get("dataStreams", []) if streams.ok else []:
                    mid = s.get("webStreamData", {}).get("measurementId")
                    if mid:
                        out[mid] = pid
        token = j.get("nextPageToken")
        if not token:
            return out


def live_tags(domain: str, get=requests.get) -> dict:
    """The Analytics tag IDs and Tag Manager containers on the site's homepage."""
    try:
        html = get(f"https://{domain}/", headers={"User-Agent": BROWSER}, timeout=40).text
    except requests.RequestException:
        return {"checked": False, "ga": [], "gtm": []}
    return {"checked": True, "ga": sorted(set(TAG.findall(html))), "gtm": sorted(set(GTM.findall(html)))}


def _report(session, pid: str, body: dict) -> list[list[str]]:
    rows, offset = [], 0
    while True:
        resp = session.post(API.format(pid=pid), json={**body, "limit": PAGE_SIZE, "offset": offset}, timeout=120)
        if resp.status_code == 403:
            raise PermissionError(f"no access to property {pid} (add the service account as a Viewer)")
        resp.raise_for_status()
        j = resp.json()
        batch = [[d["value"] for d in r.get("dimensionValues", [])] + [m["value"] for m in r.get("metricValues", [])] for r in j.get("rows", [])]
        rows += batch
        offset += len(batch)
        if not batch or offset >= int(j.get("rowCount", 0)):
            return rows


def _host_filter(domain: str) -> dict:
    host = domain.lower().removeprefix("www.")
    return {"filter": {"fieldName": "hostName", "inListFilter": {"values": [host, f"www.{host}"]}}}


def _and(*filters) -> dict:
    return {"andGroup": {"expressions": list(filters)}}


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _page(path: str) -> str:
    """A landing page or page path as the engine expects it: /path/ with a trailing slash."""
    path = (path or "").split("?")[0].strip()
    if not path.startswith("/"):
        return ""
    return path if path.endswith("/") or "." in path.rsplit("/", 1)[-1] else path + "/"


def pull_property(session, pid: str, domain: str, start: date, end: date) -> dict:
    dr = [{"startDate": start.isoformat(), "endDate": end.isoformat()}]
    host = _host_filter(domain)
    organic = {"filter": {"fieldName": "sessionDefaultChannelGroup", "stringFilter": {"value": "Organic Search"}}}
    landing = _report(session, pid, {"dateRanges": dr, "dimensions": [{"name": "landingPage"}],
                                     "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}], "dimensionFilter": _and(host, organic)})
    clicks = _report(session, pid, {"dateRanges": dr, "dimensions": [{"name": "pagePath"}], "metrics": [{"name": "eventCount"}],
                                    "dimensionFilter": _and(host, {"filter": {"fieldName": "eventName", "stringFilter": {"value": "click"}}},
                                                            {"filter": {"fieldName": "linkDomain", "stringFilter": {"matchType": "FULL_REGEXP", "value": AMAZON_LINK}}})})
    sources = _report(session, pid, {"dateRanges": dr, "dimensions": [{"name": "sessionSource"}, {"name": "sessionMedium"}, {"name": "sessionDefaultChannelGroup"}],
                                     "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}], "dimensionFilter": host})
    daily = _report(session, pid, {"dateRanges": [{"startDate": (end - timedelta(days=89)).isoformat(), "endDate": end.isoformat()}],
                                   "dimensions": [{"name": "date"}, {"name": "sessionDefaultChannelGroup"}],
                                   "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}], "dimensionFilter": host})
    # Session counts are estimates that do not add up across rows, so totals come from GA4 itself.
    def total(extra=None):
        rows = _report(session, pid, {"dateRanges": dr, "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}],
                                      "dimensionFilter": _and(host, extra) if extra else host})
        return (int(rows[0][0]), int(rows[0][1])) if rows else (0, 0)
    sessions_total, engaged_total = total()
    organic_total = total(organic)[0]
    by_day: dict[str, dict] = {}
    for d, channel, s, e in daily:
        row = by_day.setdefault(d, {"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "sessions": 0, "engaged_sessions": 0, "organic_sessions": 0})
        row["sessions"] += int(s)
        row["engaged_sessions"] += int(e)
        if channel == "Organic Search":
            row["organic_sessions"] += int(s)
    merged: dict[str, dict] = {}
    for path, s, e in landing:
        page = _page(path)
        if page:
            m = merged.setdefault(page, {"page": page, "sessions": 0, "engaged_sessions": 0})
            m["sessions"] += int(s)
            m["engaged_sessions"] += int(e)
    amazon: dict[str, int] = {}
    for path, n in clicks:
        page = _page(path)
        if page:
            amazon[page] = amazon.get(page, 0) + int(n)
    return {
        "sessions": sorted(merged.values(), key=lambda r: -r["sessions"]),
        "amazon_clicks": sorted(({"page": k, "amazon_clicks": v} for k, v in amazon.items()), key=lambda r: -r["amazon_clicks"]),
        "sources": sorted(({"source": s, "medium": m, "channel": c, "sessions": int(n), "engaged_sessions": int(e)} for s, m, c, n, e in sources),
                          key=lambda r: -r["sessions"]),
        "daily": sorted(by_day.values(), key=lambda r: r["date"]),
        "totals": {"sessions": sessions_total, "engaged_sessions": engaged_total, "organic_sessions": organic_total},
    }


def pull(sites, days: int = 28, root: str | Path = "data/ga4", session=None, today: date | None = None, log=print,
         get=requests.get) -> dict[str, dict]:
    session = session or gcp.session(SCOPE)
    today = today or date.today()
    try:
        streams = readable_streams(session)
    except Exception as exc:
        log(f"Analytics: could not list readable properties ({exc}); using sites.yaml only")
        streams = {}
    end = today - timedelta(days=2)  # GA4 is still processing yesterday; its numbers would move after the pull
    start = end - timedelta(days=days - 1)
    out = {}
    for site in sites:
        configured = [str(p) for p in (getattr(site, "ga4_properties", None) or [])]
        tags = live_tags(site.domain, get=get)
        tagged = [streams[m] for m in tags["ga"] if m in streams]
        unreadable = [m for m in tags["ga"] if m not in streams]
        props = list(dict.fromkeys(tagged + configured))
        if not props:
            continue
        chosen, notes, data = None, [], None
        if tags["checked"] and not tags["ga"] and not tags["gtm"]:
            notes.append("no Google Analytics tag ID in the homepage HTML (a script-loaded tag would not show)")
        for m in unreadable:
            notes.append(f"the site's tag {m} belongs to a property this service account cannot read")
        for pid in props:
            try:
                result = pull_property(session, pid, site.domain, start, end)
            except PermissionError as exc:
                notes.append(str(exc))
                continue
            except Exception as exc:
                notes.append(f"property {pid}: {exc}")
                continue
            if result["totals"]["sessions"]:
                chosen, data = pid, result
                break
            notes.append(f"property {pid} recorded no visits for {site.domain}")
            data = data or result
            chosen = chosen or pid
        folder = Path(root) / site.domain
        if data is None:
            log(f"[{site.domain}] Analytics: nothing readable ({'; '.join(notes)})")
            (folder / "meta.json").parent.mkdir(parents=True, exist_ok=True)
            (folder / "meta.json").write_text(json.dumps({"property": None, "tags": tags, "unreadable_tags": unreadable, "start": start.isoformat(),
                                                          "end": end.isoformat(), "pulled": today.isoformat(), "notes": notes, "sessions": 0}, indent=1))
            out[site.domain] = {"property": None, "sessions": 0, "notes": notes, "tags": tags}
            continue
        _write(folder / "sessions.csv", ["page", "sessions", "engaged_sessions"], data["sessions"])
        _write(folder / "amazon_clicks.csv", ["page", "amazon_clicks"], data["amazon_clicks"])
        _write(folder / "sources.csv", ["source", "medium", "channel", "sessions", "engaged_sessions"], data["sources"])
        _write(folder / "daily.csv", ["date", "sessions", "engaged_sessions", "organic_sessions"], data["daily"])
        total, organic = data["totals"]["sessions"], data["totals"]["organic_sessions"]
        meta = {"property": chosen, "tags": tags, "unreadable_tags": unreadable,
                "start": start.isoformat(), "end": end.isoformat(), "pulled": today.isoformat(),
                "sessions": total, "organic_sessions": organic, "engaged_sessions": data["totals"]["engaged_sessions"],
                "amazon_clicks": sum(r["amazon_clicks"] for r in data["amazon_clicks"]), "notes": notes,
                "note": "Google Analytics Data API. Totals are GA4's own; rows are estimates and may not add up to them. "
                        "Sessions by landing page are organic search only."}
        (folder / "meta.json").write_text(json.dumps(meta, indent=1))
        for stale in ("sessions.meta.txt", ".gitkeep"):
            (folder / stale).unlink(missing_ok=True)
        out[site.domain] = meta
        log(f"[{site.domain}] Analytics {chosen}: {total} sessions ({organic} organic), {meta['amazon_clicks']} Amazon clicks"
            + (f"; {'; '.join(notes)}" if notes else ""))
    return out


def load_meta(domain: str, root: str | Path = "data/ga4") -> dict | None:
    path = Path(root) / domain / "meta.json"
    return json.loads(path.read_text()) if path.exists() else None
