"""Pull page-level Search Console data with a Google service account.

Setup (one time):
  1. Google Cloud console: create a service account, enable the "Google Search Console API",
     download the JSON key.
  2. Search Console > Settings > Users and permissions: add the service account's email as a
     Restricted user on every property in sites.yaml.
  3. Provide the key JSON in the GSC_SERVICE_ACCOUNT_JSON environment variable
     (a GitHub Actions secret for the scheduled run). Never commit the key.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

API = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
PAGE_SIZE = 25000


def authed_session():
    """Build an authorised requests session from GSC_SERVICE_ACCOUNT_JSON."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise SystemExit("GSC_SERVICE_ACCOUNT_JSON is not set. See ace/gsc.py for setup.")
    creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=[SCOPE])
    return AuthorizedSession(creds)


def query_pages(session, gsc_property: str, start: date, end: date) -> list[dict]:
    """Return [{page, clicks, impressions, position}] for the date range, following pagination."""
    url = API.format(site=quote(gsc_property, safe=""))
    rows, offset = [], 0
    while True:
        body = {
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": ["page"], "rowLimit": PAGE_SIZE, "startRow": offset,
        }
        resp = session.post(url, json=body, timeout=60)
        resp.raise_for_status()
        batch = resp.json().get("rows", [])
        rows += [
            {"page": r["keys"][0], "clicks": r["clicks"], "impressions": r["impressions"], "position": r["position"]}
            for r in batch
        ]
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def pull(sites, days: int = 28, root: str | Path = "data/gsc", session=None, today: date | None = None, log=print) -> None:
    """Write data/gsc/<domain>/pages.csv and meta.json for every site that has a gsc_property."""
    session = session or authed_session()
    end = (today or date.today()) - timedelta(days=3)  # Search Console data lags by 2-3 days
    start = end - timedelta(days=days - 1)
    for site in sites:
        if not site.gsc_property:
            continue
        try:
            rows = query_pages(session, site.gsc_property, start, end)
        except Exception as exc:  # one inaccessible property must not stop the rest
            log(f"[{site.domain}] Search Console pull failed: {exc}")
            continue
        folder = Path(root) / site.domain
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "pages.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["page", "clicks", "impressions", "position"])
            w.writeheader()
            w.writerows(rows)
        (folder / "meta.json").write_text(json.dumps(
            {"start": start.isoformat(), "end": end.isoformat(), "note": "Search Console API, all pages"}
        ))
        log(f"[{site.domain}] {len(rows)} pages from Search Console")
