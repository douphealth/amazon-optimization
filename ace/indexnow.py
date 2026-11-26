"""Tell search engines which pages are new or changed, through IndexNow.

IndexNow is read by Bing, Yandex, Seznam, Naver and the engines that use Bing's index. Google does
not take part. One POST per site lists the URLs; the engines then decide when to crawl them.

Requirements per site: the file https://<host>/<key>.txt must exist and contain exactly <key>.
The key comes from the INDEXNOW_KEY environment variable and is never written to the repository.

Only pages that changed since the last successful submission are sent (the first run sends every
indexable page once). State lives in data/indexnow/<domain>.json.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .score import Row

ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 10000  # IndexNow's limit per request
NOT_SUBMITTABLE = {"noindex", "canonical_elsewhere", "redirects"}
MEANING = {
    200: "accepted", 202: "accepted, key check pending", 400: "bad request",
    403: "key not valid for this host", 422: "URLs do not match the host or key", 429: "too many requests",
}


@dataclass
class Batch:
    domain: str
    host: str
    urls: list[str] = field(default_factory=list)
    unchanged: int = 0
    status: str = "planned"
    detail: str = ""


def fingerprint(row: Row) -> str:
    """Changes when the page's title or text changes."""
    raw = row.page.title + "|" + ",".join(map(str, row.page.sketch))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def eligible(row: Row) -> bool:
    """Only pages a search engine should index: they load, allow indexing and are their own canonical."""
    return row.page.status == 200 and not NOT_SUBMITTABLE & set(row.issues)


def load_state(domain: str, root: Path) -> dict[str, str]:
    path = root / f"{domain}.json"
    return json.loads(path.read_text()).get("submitted", {}) if path.exists() else {}


def plan(rows: list[Row], root: Path = Path("data/indexnow"), sites: list[str] | None = None) -> tuple[list[Batch], dict]:
    """Group new or changed indexable pages by host. Returns (batches, fingerprints to save on success)."""
    by_host: dict[tuple[str, str], Batch] = {}
    prints: dict[str, dict[str, str]] = defaultdict(dict)
    states: dict[str, dict[str, str]] = {}
    for row in rows:
        domain = row.site.domain
        if (sites and domain not in sites) or not eligible(row):
            continue
        state = states.setdefault(domain, load_state(domain, root))
        host = urlsplit(row.page.url).netloc
        batch = by_host.setdefault((domain, host), Batch(domain=domain, host=host))
        mark = fingerprint(row)
        if state.get(row.page.url) == mark:
            batch.unchanged += 1
            continue
        batch.urls.append(row.page.url)
        prints[domain][row.page.url] = mark
    return list(by_host.values()), prints


def key_file_ok(host: str, key: str, get=requests.get) -> bool:
    try:
        resp = get(f"https://{host}/{key}.txt", timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        return resp.status_code == 200 and resp.text.strip() == key
    except requests.RequestException:
        return False


def run(
    rows: list[Row], out: Path, apply: bool = False, sites: list[str] | None = None,
    root: Path = Path("data/indexnow"), key: str | None = None, get=requests.get, post=requests.post, log=print,
) -> list[Batch]:
    key = key if key is not None else os.environ.get("INDEXNOW_KEY", "")
    batches, prints = plan(rows, root, sites)
    for batch in batches:
        if not batch.urls:
            batch.status = "nothing_new"
            continue
        if not key:
            batch.status, batch.detail = "no_key", "INDEXNOW_KEY is not set"
            continue
        if not key_file_ok(batch.host, key, get):
            batch.status = "key_file_invalid"
            batch.detail = f"https://{batch.host}/<key>.txt does not return the key, so engines would reject the submission"
            continue
        if not apply:
            batch.status = "would_submit"
            continue
        codes = []
        for i in range(0, len(batch.urls), BATCH):
            body = {"host": batch.host, "key": key, "keyLocation": f"https://{batch.host}/{key}.txt", "urlList": batch.urls[i:i + BATCH]}
            try:
                codes.append(post(ENDPOINT, json=body, timeout=60, headers={"Content-Type": "application/json; charset=utf-8"}).status_code)
            except requests.RequestException as exc:
                codes.append(0)
                batch.detail = type(exc).__name__
        ok = all(c in (200, 202) for c in codes)
        batch.status = "submitted" if ok else "rejected"
        batch.detail = batch.detail or ", ".join(f"HTTP {c} {MEANING.get(c, '')}".strip() for c in sorted(set(codes)))
        if ok:
            state = load_state(batch.domain, root)
            state.update({u: prints[batch.domain][u] for u in batch.urls})
            root.mkdir(parents=True, exist_ok=True)
            (root / f"{batch.domain}.json").write_text(json.dumps({"last_submission": out.name, "submitted": state}, indent=0, sort_keys=True))
    write_log(out, batches)
    return batches


LOG_FIELDS = ["site", "host", "status", "urls_new_or_changed", "urls_unchanged", "detail"]


def write_log(out: Path, batches: list[Batch]) -> None:
    """Write indexnow-log.csv. A later run that finds nothing new keeps the earlier "submitted" row."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / "indexnow-log.csv"
    rows: dict[str, dict] = {}
    if path.exists():
        with path.open() as f:
            rows = {r["host"]: r for r in csv.DictReader(f)}
    for b in batches:
        if b.status == "nothing_new" and rows.get(b.host, {}).get("status") == "submitted":
            continue
        rows[b.host] = dict(zip(LOG_FIELDS, [b.domain, b.host, b.status, len(b.urls), b.unchanged, b.detail]))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        w.writerows(rows.values())


def summarize(batches: list[Batch]) -> str:
    return "\n".join(f"{b.host:36} {b.status:18} new/changed={len(b.urls):5} unchanged={b.unchanged:5} {b.detail}" for b in batches) or "nothing to submit"
