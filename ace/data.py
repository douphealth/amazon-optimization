"""Read the first-party data sources: Search Console, Bing Webmaster, Google Analytics and Amazon
Associates reports. `ace pull` writes the first three; any of them may also be dropped in by hand.

Both readers accept the files as exported by the vendor UI, so no API access is required:
  data/gsc/<domain>/pages.csv         Search Console > Performance > Export > Pages.csv
  data/associates/*.csv               Associates Central > Reports > Tracking ID summary > Download
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import norm_url


@dataclass
class GscRow:
    clicks: float = 0
    impressions: float = 0
    position: float = 0


def _num(value: str) -> float:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _find(header: list[str], *needles: str) -> int | None:
    """Index of the first column whose lowercased name contains one of the needles."""
    lowered = [h.strip().lower() for h in header]
    for needle in needles:
        for i, h in enumerate(lowered):
            if needle in h:
                return i
    return None


def load_gsc(domain: str, root: str | Path = "data/gsc") -> tuple[dict[str, GscRow], dict]:
    """Return ({normalised url: GscRow}, meta). URL-fragment rows are dropped: Search Console
    reports jump links as separate rows and adding them would double count the page."""
    folder = Path(root) / domain
    path = folder / "pages.csv"
    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if not path.exists():
        return {}, meta
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    if not rows:
        return {}, meta
    header = rows[0]
    c_page = _find(header, "page", "url")
    c_clicks, c_impr, c_pos = _find(header, "clicks"), _find(header, "impressions"), _find(header, "position")
    if None in (c_page, c_clicks, c_impr, c_pos):
        raise ValueError(f"{path}: need page, clicks, impressions and position columns, got {header}")
    out: dict[str, GscRow] = {}
    for row in rows[1:]:
        if len(row) <= max(c_page, c_clicks, c_impr, c_pos) or "#" in row[c_page]:
            continue
        _add(out, norm_url(row[c_page]), _num(row[c_clicks]), _num(row[c_impr]), _num(row[c_pos]))
    return out, meta


def _add(out: dict[str, GscRow], key: str, clicks: float, impressions: float, position: float) -> None:
    """Merge a row into `out`. Rows whose URLs differ only by www, a trailing slash or a query string
    belong to the same page: clicks and impressions add up, position is impression-weighted."""
    if key not in out:
        out[key] = GscRow(clicks, impressions, position)
        return
    old = out[key]
    weight = old.impressions + impressions
    pos = (old.position * old.impressions + position * impressions) / weight if weight else (old.position or position)
    out[key] = GscRow(old.clicks + clicks, weight, round(pos, 2))


def load_bing(domain: str, root: str | Path = "data/bing") -> tuple[dict[str, GscRow], dict]:
    """({normalised url: GscRow}, meta) from data/bing/<domain>/ (written by `ace pull`)."""
    folder = Path(root) / domain
    meta = json.loads((folder / "meta.json").read_text()) if (folder / "meta.json").exists() else {}
    path = folder / "pages.csv"
    if not path.exists():
        return {}, meta
    out: dict[str, GscRow] = {}
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))):
        page = (row.get("page") or "").strip()
        if page and "#" not in page:
            _add(out, norm_url(page), _num(row.get("clicks", "")), _num(row.get("impressions", "")), _num(row.get("position", "")))
    return out, meta


def load_ga4(domain: str, root: str | Path = "data/ga4") -> dict[str, dict]:
    """Per-page numbers from Google Analytics, keyed by normalised URL.

    data/ga4/<domain>/amazon_clicks.csv   page,amazon_clicks   outbound clicks to Amazon
    data/ga4/<domain>/sessions.csv        page,sessions        visits that landed on the page

    `page` is a path (/review/x/) or a full URL. Either file may be missing. Unlike Search
    Console this counts visitors from every source, so it shows pages Google never sends anyone to."""
    out: dict[str, dict] = {}
    for name, key in (("amazon_clicks.csv", "amazon_clicks"), ("sessions.csv", "sessions")):
        path = Path(root) / domain / name
        if not path.exists():
            continue
        for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))):
            page = (row.get("page") or "").strip()
            if not page or "#" in page:
                continue
            url = page if page.startswith("http") else f"https://{domain}{page}"
            entry = out.setdefault(norm_url(url), {"url": url, "amazon_clicks": 0.0, "sessions": 0.0})
            entry[key] += _num(row.get(key, ""))
    return out


@dataclass
class TagStats:
    clicks: float = 0
    items: float = 0
    earnings: float = 0

    @property
    def epc(self) -> float | None:
        return self.earnings / self.clicks if self.clicks else None


def load_associates(root: str | Path = "data/associates") -> dict[str, TagStats]:
    """Sum clicks, items and earnings per tracking ID across every CSV in the folder.

    Column names differ between Associates report types, so columns are matched by keyword
    and the header row is located by searching for one that mentions both tracking and clicks.
    """
    stats: dict[str, TagStats] = {}
    for path in sorted(Path(root).glob("*.csv")):
        rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
        start = next(
            (i for i, r in enumerate(rows) if _find(r, "tracking") is not None and _find(r, "clicks") is not None),
            None,
        )
        if start is None:
            continue
        header = rows[start]
        c_tag, c_clicks = _find(header, "tracking"), _find(header, "clicks")
        c_items = _find(header, "items shipped", "shipped items", "ordered items", "items ordered")
        c_earn = _find(header, "total earnings", "earnings", "ad fees", "commission")
        for row in rows[start + 1:]:
            if len(row) <= c_tag or not row[c_tag].strip():
                continue
            s = stats.setdefault(row[c_tag].strip(), TagStats())
            s.clicks += _num(row[c_clicks]) if len(row) > c_clicks else 0
            if c_items is not None and len(row) > c_items:
                s.items += _num(row[c_items])
            if c_earn is not None and len(row) > c_earn:
                s.earnings += _num(row[c_earn])
    return stats


def ensure_folders(domains: list[str], root: str | Path = "data") -> None:
    """Make sure each site has its data folders, so the dashboard's upload links have a target.
    Git does not keep empty folders, hence the placeholder file."""
    root = Path(root)
    for folder in [root / "associates", *(root / kind / d for kind in ("gsc", "ga4") for d in domains)]:
        folder.mkdir(parents=True, exist_ok=True)
        if not any(folder.iterdir()):
            (folder / ".gitkeep").touch()
