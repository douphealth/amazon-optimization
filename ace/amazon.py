"""Amazon Creators API client: product search and product data for the product boxes.

The Creators API replaced the Product Advertising API 5.0, which Amazon shut off on 2026-05-15.
Credentials are a Login with Amazon client (Associates Central > Tools > Creators API):

    AMAZON_CREATORS_CREDENTIAL_ID      amzn1.application-oa2-client....
    AMAZON_CREATORS_CREDENTIAL_SECRET  amzn1.oa2-cs.v1....
    AMAZON_CREATORS_VERSION            3.1 (North America, the default), 3.2 (Europe) or 3.3 (Far East)

How the API is used, per Amazon's documentation:
- one access token per hour (client credentials, scope creatorsapi::default), cached;
- calls spread at most one per second (new credentials start at 1 TPS / 8640 per day);
- 429 and 5xx retried with backoff, honouring retryAfterSeconds;
- product data cached for one day at most (Amazon's guidance for item info and images);
- the partnerTag is the site's own tracking ID, and the product link Amazon returns
  (detailPageURL) is used unchanged, so every click is attributed.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

TOKEN_URLS = {
    "3.1": "https://api.amazon.com/auth/o2/token",
    "3.2": "https://api.amazon.co.uk/auth/o2/token",
    "3.3": "https://api.amazon.co.jp/auth/o2/token",
}
API = "https://creatorsapi.amazon/catalog/v1"
RESOURCES = [
    "itemInfo.title", "itemInfo.byLineInfo", "itemInfo.features",
    "images.primary.medium", "images.primary.large",
    "offersV2.listings.availability", "offersV2.listings.isBuyBoxWinner",
    "browseNodeInfo.browseNodes", "browseNodeInfo.websiteSalesRank",
]
ITEM_TTL = 24 * 3600
UNAVAILABLE = {"OUT_OF_STOCK", "UNAVAILABLE", "DISCONTINUED"}


class AmazonError(RuntimeError):
    pass


@dataclass
class Item:
    asin: str
    title: str = ""
    url: str = ""          # Amazon's own product link, with the partner tag
    image: str = ""        # 160 px image (medium)
    image_w: int = 0
    image_h: int = 0
    image_large: str = ""  # 500 px image
    brand: str = ""
    available: bool = False
    buybox: bool = False
    sales_rank: int = 0    # 0 = not reported
    nodes: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)


def parse_item(raw: dict) -> Item:
    info = raw.get("itemInfo") or {}
    img = ((raw.get("images") or {}).get("primary") or {})
    medium, large = img.get("medium") or {}, img.get("large") or {}
    listings = (raw.get("offersV2") or {}).get("listings") or []
    first = listings[0] if listings else {}
    avail = first.get("availability")
    avail_type = (avail.get("type") if isinstance(avail, dict) else avail) or ""
    nodes_info = raw.get("browseNodeInfo") or {}
    rank = (nodes_info.get("websiteSalesRank") or {}).get("salesRank") or 0
    byline = info.get("byLineInfo") or {}
    brand = ((byline.get("brand") or {}).get("displayValue") or (byline.get("manufacturer") or {}).get("displayValue") or "")
    return Item(
        asin=raw.get("asin", ""),
        title=((info.get("title") or {}).get("displayValue") or "").strip(),
        url=raw.get("detailPageURL") or "",
        image=medium.get("url") or "", image_w=int(medium.get("width") or 0), image_h=int(medium.get("height") or 0),
        image_large=large.get("url") or "",
        brand=brand.strip(),
        # Offers are listed for products Amazon or a seller can ship; none, or an out-of-stock
        # type, means a reader could not buy it today.
        available=bool(listings) and str(avail_type).upper() not in UNAVAILABLE,
        buybox=bool(first.get("isBuyBoxWinner")),
        sales_rank=int(rank or 0),
        nodes=[n.get("displayName") or n.get("contextFreeName") or "" for n in (nodes_info.get("browseNodes") or [])],
        features=list(((info.get("features") or {}).get("displayValues") or [])[:5]),
    )


class Creators:
    def __init__(self, credential_id: str, credential_secret: str, version: str = "3.1",
                 marketplace: str = "www.amazon.com", cache_dir: Path | None = Path("data/amazon/cache"),
                 min_interval: float = 1.05, session=None, clock=time.time, sleep=time.sleep, log=print):
        if version not in TOKEN_URLS:
            raise AmazonError(f"Unsupported credential version {version}: use 3.1, 3.2 or 3.3")
        self.credential_id, self.credential_secret = credential_id, credential_secret
        self.token_url, self.marketplace = TOKEN_URLS[version], marketplace
        self.cache_dir = cache_dir
        self.min_interval, self.http = min_interval, session or requests.Session()
        self.clock, self.sleep, self.log = clock, sleep, log
        self._token, self._token_until, self._last = "", 0.0, 0.0
        self._lock = threading.Lock()
        self.calls = 0
        self.failures = 0     # calls that failed after every retry, in a row
        self.broken = False   # after 3 such failures every later call fails fast: Amazon is down or the quota is spent

    @classmethod
    def from_env(cls, **kw) -> "Creators | None":
        cid, secret = os.environ.get("AMAZON_CREATORS_CREDENTIAL_ID"), os.environ.get("AMAZON_CREATORS_CREDENTIAL_SECRET")
        if not cid or not secret:
            return None
        return cls(cid, secret, os.environ.get("AMAZON_CREATORS_VERSION", "3.1"), **kw)

    # ---------- transport ----------

    def token(self) -> str:
        if self._token and self.clock() < self._token_until:
            return self._token
        r = self.http.post(self.token_url, json={"grant_type": "client_credentials", "client_id": self.credential_id,
                                                 "client_secret": self.credential_secret, "scope": "creatorsapi::default"}, timeout=30)
        if r.status_code != 200:
            raise AmazonError(f"token request failed: HTTP {r.status_code} {r.text[:200]}")
        body = r.json()
        self._token = body["access_token"]
        self._token_until = self.clock() + int(body.get("expires_in", 3600)) - 120
        return self._token

    def _post(self, op: str, body: dict, attempts: int = 6) -> dict:
        if self.broken:
            raise AmazonError(f"{op}: skipped, the Creators API failed repeatedly in this run")
        try:
            result = self._post_once(op, body, attempts)
        except AmazonError as exc:
            if "ValidationException" not in str(exc):  # a rejected request is not an outage
                self.failures += 1
                self.broken = self.failures >= 3
            raise
        self.failures = 0
        return result

    def _post_once(self, op: str, body: dict, attempts: int) -> dict:
        refreshed = False
        for attempt in range(attempts):
            with self._lock:  # one call at a time, spaced out: excess calls in a second are throttled
                wait = self._last + self.min_interval - self.clock()
                if wait > 0:
                    self.sleep(wait)
                self._last = self.clock()
            self.calls += 1
            try:
                r = self.http.post(f"{API}/{op}", json=body, timeout=30, headers={
                    "Authorization": f"Bearer {self.token()}", "Content-Type": "application/json", "x-marketplace": self.marketplace})
            except requests.RequestException as exc:
                if attempt == attempts - 1:
                    raise AmazonError(f"{op}: {exc}") from exc
                self.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            try:
                err = r.json()
            except ValueError:
                err = {"message": r.text[:200]}
            if r.status_code == 401 and not refreshed:  # token expired early or was revoked
                self._token, refreshed = "", True
                continue
            if r.status_code == 404:  # "No items found" is an answer, not a failure
                return {}
            if r.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                self.sleep(min(120.0, float(err.get("retryAfterSeconds") or min(60, 2 ** (attempt + 1)))))
                continue
            raise AmazonError(f"{op}: HTTP {r.status_code} {err.get('type', '')} {err.get('reason', '')} {err.get('message', '')}".strip())
        raise AmazonError(f"{op}: gave up after {attempts} attempts")

    # ---------- cache ----------

    def _cache_path(self, kind: str, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / kind / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")

    def _cached(self, kind: str, key: str):
        path = self._cache_path(kind, key)
        if path and path.exists():
            try:
                data = json.loads(path.read_text())
                if self.clock() - data.get("at", 0) < ITEM_TTL:
                    return data["value"]
            except (ValueError, KeyError, OSError):
                path.unlink(missing_ok=True)  # a half-written file: ask Amazon again
        return None

    def _store(self, kind: str, key: str, value) -> None:
        path = self._cache_path(kind, key)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"at": self.clock(), "value": value}))
            tmp.replace(path)  # atomic: a reader never sees half a file

    # ---------- operations ----------

    def get_items(self, asins: list[str], tag: str) -> dict[str, Item]:
        """Product data for these ASINs, keyed by ASIN. Unknown or unsellable ASINs are absent."""
        out: dict[str, Item] = {}
        todo = []
        for asin in dict.fromkeys(a.upper() for a in asins if a):
            hit = self._cached("item", f"{tag}:{asin}")
            if hit is None:
                todo.append(asin)
            elif hit:
                out[asin] = Item(**hit)
        for i in range(0, len(todo), 10):  # ten ASINs count as one call
            batch = todo[i:i + 10]
            data = self._post("getItems", {"partnerTag": tag, "marketplace": self.marketplace, "itemIds": batch,
                                           "itemIdType": "ASIN", "condition": "New", "resources": RESOURCES})
            found = {it.asin: it for it in map(parse_item, ((data.get("itemsResult") or data.get("itemResults") or {}).get("items") or []))}
            for asin in batch:
                item = found.get(asin)
                self._store("item", f"{tag}:{asin}", asdict(item) if item else {})
                if item:
                    out[asin] = item
        return out

    def search(self, keywords: str, tag: str, index: str = "All", count: int = 10) -> list[Item]:
        """Products for a search phrase, in Amazon's relevance order, in stock only."""
        key = f"{tag}:{index}:{count}:{keywords.lower().strip()}"
        hit = self._cached("search", key)
        if hit is not None:
            return [Item(**h) for h in hit]
        data = self._post("searchItems", {"partnerTag": tag, "marketplace": self.marketplace, "keywords": keywords,
                                          "searchIndex": index or "All", "itemCount": max(1, min(10, count)),
                                          "availability": "Available", "condition": "New", "resources": RESOURCES})
        items = [parse_item(r) for r in ((data.get("searchResult") or {}).get("items") or [])]
        self._store("search", key, [asdict(i) for i in items])
        for item in items:  # a search answer is fresh product data too
            self._store("item", f"{tag}:{item.asin}", asdict(item))
        return items
