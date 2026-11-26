"""Draft an above-the-fold product box for pages whose Amazon links sit too deep.

The box only reuses products that are already linked on that page, with the page's own tag,
so it introduces no new product claims. Output is a draft for review: nothing is published.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urlsplit

from .score import Row

MAX_PRODUCTS = 4

BOX_COMMENT = """<!--
Draft for: {url}
Why: {why}
Where: paste in Classic Editor (Text mode) right after the opening answer paragraph, before the first H2.
Before publishing: open every link once and confirm the product is still sold. The names below were
read from this page's own link text and image alt text.
Rollback: delete this <div>.
-->
"""

BOX_DIV = """<div class="ace-quick-picks" style="border:1px solid #d9d9d9;border-left:4px solid #2f7d32;background:#f7faf7;padding:14px 16px;margin:18px 0;border-radius:6px">
<p style="margin:0 0 8px;font-weight:700">{heading}</p>
<ul style="margin:0 0 10px 18px;padding:0">
{items}
</ul>
<p style="margin:0;font-size:13px;color:#555">As an Amazon Associate, {site} earns from qualifying purchases.</p>
</div>
"""


def short_name(name: str, limit: int = 70) -> str:
    """Trim marketplace-style titles: keep the part before the first comma, cap the length."""
    name = re.sub(r"\s+product image from Amazon$", "", name.strip(), flags=re.I)
    name = name.split(",")[0].strip()
    if len(name) > limit:
        name = name[:limit].rsplit(" ", 1)[0]
    return name


CURATED = Path("boxes")  # hand-written boxes: boxes/<domain>/<url-slug>.html


def curated(row: Row, root: Path = CURATED) -> str | None:
    """A hand-written box for this page, if one exists. It overrides the generated one."""
    slug = urlsplit(row.page.url).path.strip("/").replace("/", "__") or "home"
    path = root / row.site.domain / f"{slug}.html"
    return path.read_text() if path.exists() else None


def box(row: Row, blocked: frozenset[str] | set[str] = frozenset()) -> str | None:
    """Return the box <div>, or None if the page has fewer than two nameable, non-blocked products."""
    seen, items = set(), []
    for link in row.page.content_links:
        if link.kind != "product" or link.asin in seen or link.asin in blocked or not link.tag:
            continue
        name = short_name(link.name)
        if not name:
            continue
        seen.add(link.asin)
        url = f"https://www.amazon.com/dp/{link.asin}?tag={link.tag}"
        items.append(
            f'<li><a href="{html.escape(url)}" rel="sponsored nofollow noopener" target="_blank">{html.escape(name)}</a></li>'
        )
        if len(items) == MAX_PRODUCTS:
            break
    if len(items) < 2:
        return None
    return BOX_DIV.format(heading="Quick picks from this guide", items="\n".join(items), site=row.site.name)


def draft(row: Row, blocked: frozenset[str] | set[str] = frozenset()) -> str | None:
    """The box plus a comment telling a human where to paste it."""
    div = box(row, blocked)
    if div is None:
        return None
    depth = row.page.first_link_depth or 0
    comment = BOX_COMMENT.format(url=row.page.url, why=f"first Amazon link is {depth:.0%} of the way down the article")
    return comment + div


def write_fixes(rows: list[Row], out_dir: Path, top: int = 25, blocked: set[str] | None = None) -> list[Path]:
    """Write drafts for the highest-scoring pages that have late links. Returns the files written."""
    written = []
    candidates = [r for r in rows if {"first_link_late", "first_link_very_late"} & set(r.issues)]
    candidates.sort(key=lambda r: (-r.score, -(r.page.first_link_depth or 0)))
    for row in candidates[:top]:
        text = draft(row, blocked or set())
        if not text:
            continue
        slug = urlsplit(row.page.url).path.strip("/").replace("/", "__") or "home"
        path = out_dir / row.site.domain / f"{slug}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        written.append(path)
    return written
