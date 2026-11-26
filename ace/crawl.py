"""Discover a site's URLs from its sitemaps and fetch + parse every page."""
from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import requests

from .config import Site
from .page import Page, parse

_local = threading.local()


def _session(ua: str) -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update({"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"})
    return _local.s


def fetch(url: str, ua: str, timeout: int = 25, tries: int = 3) -> requests.Response | None:
    """GET with backoff on 429/5xx and network errors. Returns None if every try failed."""
    for attempt in range(tries):
        try:
            r = _session(ua).get(url, timeout=timeout)
            if r.status_code not in (429, 500, 502, 503, 504):
                return r
        except requests.RequestException:
            r = None
        if attempt < tries - 1:
            time.sleep(2 ** attempt)
    return r


def _locs(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (child sitemaps, page URLs) from a sitemap or sitemap index."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8", "ignore"))
    except ET.ParseError:
        return [], []
    children, urls = [], []
    for el in root:
        kind = el.tag.rsplit("}", 1)[-1]
        loc = next((c.text for c in el if c.tag.rsplit("}", 1)[-1] == "loc" and c.text), None)
        if not loc:
            continue
        (children if kind == "sitemap" else urls).append(loc.strip())
    return children, urls


def discover(site: Site) -> dict[str, list[str]]:
    """Map every page URL to the sitemap(s) that list it."""
    roots = list(site.sitemaps)
    if not roots:
        robots = fetch(f"https://{site.domain}/robots.txt", site.user_agent)
        if robots is not None and robots.ok:
            # Some sites write a relative path here, so resolve it against the domain.
            roots = [urljoin(f"https://{site.domain}/", u) for u in re.findall(r"(?im)^sitemap:\s*(\S+)", robots.text)]
    if not roots:
        roots = [f"https://{site.domain}/{p}" for p in ("sitemap_index.xml", "sitemap.xml", "wp-sitemap.xml")]
    skip = re.compile(site.skip_sitemaps) if site.skip_sitemaps else None
    seen, queue, found = set(), list(dict.fromkeys(roots)), {}
    while queue:
        sm = queue.pop(0)
        if sm in seen or (skip and skip.search(sm)):
            continue
        seen.add(sm)
        r = fetch(sm, site.user_agent)
        if r is None or not r.ok:
            continue
        children, urls = _locs(r.text)
        queue.extend(children)
        for u in urls:
            found.setdefault(u, []).append(sm)
    return found


def audit_url(url: str, site: Site) -> Page:
    r = fetch(url, site.user_agent)
    if r is None:
        return Page(url=url, error="fetch failed")
    if not r.ok or "html" not in r.headers.get("content-type", ""):
        return Page(url=url, status=r.status_code, final_url=r.url)
    page = parse(url, r.text)
    page.status, page.final_url = r.status_code, r.url
    if "noindex" in r.headers.get("x-robots-tag", "").lower():
        page.noindex = True
    return page


def crawl(site: Site, log=print) -> tuple[list[Page], dict[str, list[str]]]:
    sitemap_map = discover(site)
    urls = list(sitemap_map)[: site.max_urls]
    log(f"[{site.domain}] {len(sitemap_map)} URLs in sitemaps, crawling {len(urls)}")
    with ThreadPoolExecutor(max_workers=site.concurrency) as pool:
        pages = list(pool.map(lambda u: audit_url(u, site), urls))
    return pages, sitemap_map
