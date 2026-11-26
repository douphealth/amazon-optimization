"""Draft an above-the-fold product box for pages whose Amazon links sit too deep.

The box only reuses products that are already linked on that page, with the page's own tag,
so it introduces no new product claims. Output is a draft for review: nothing is published.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
<ul style="list-style:none;margin:0 0 10px;padding:0">
{items}
</ul>
<p style="margin:0;font-size:13px;color:#555">As an Amazon Associate, {site} earns from qualifying purchases.</p>
</div>
"""


# Link text that is a call to action, not a product name. A box item must name the product.
NOT_A_NAME = re.compile(r"^(shop|buy|check|view|see|get|discover|learn|read|click|order|compare|find|grab)\b|[→»›>]\s*$|\bprice\b|\bamazon\b", re.I)
IMAGE_SUFFIX = re.compile(r"\s+(amazon\s+)?(product\s+)?(image|photo|picture|cover|product)(\s+(from|on)\s+amazon)?$", re.I)
DANGLING = re.compile(r"[\s,;:&/|–-]+(with|for|and|or|of|the|to|in|a|an|by|on)?$", re.I)


def short_name(name: str, limit: int = 60) -> str:
    """Turn link text or image alt text into a product name fit for a list, or "" if it is not one.

    Drops "... product image from Amazon" endings, keeps the part of a marketplace title before the
    first comma or dash, caps the length on a word boundary and never ends on "with", "for"..."""
    name = " ".join(name.split())
    for _ in range(2):
        name = IMAGE_SUFFIX.sub("", name)
    name = re.split(r",\s| [-–—|] ", name)[0].strip().rstrip("….")
    if len(name) > limit and len(name.split(":")[0].split()) >= 2:
        name = name.split(":")[0]  # a long book title: keep the part before the subtitle
    if len(name) > limit:
        name = name[:limit].rsplit(" ", 1)[0]
    if name.count("(") > name.count(")"):
        name = name[: name.rindex("(")]
    for _ in range(3):
        name = DANGLING.sub("", name)
    if len(name) < 4 or name.endswith(("!", "?")) or NOT_A_NAME.search(name) or not re.search(r"[A-Za-z]{3}", name):
        return ""
    return name


CURATED = Path("boxes")  # hand-written boxes: boxes/<domain>/<url-slug>.html


def curated(row: Row, root: Path = CURATED) -> str | None:
    """A hand-written box for this page, if one exists. It overrides the generated one."""
    slug = urlsplit(row.page.url).path.strip("/").replace("/", "__") or "home"
    path = root / row.site.domain / f"{slug}.html"
    return path.read_text() if path.exists() else None


# A heading that opens a section rather than naming a product.
HEADING_NOT_PRODUCT = re.compile(
    r"^(why|how|what|when|where|who|which|is|are|can|do|does|should|our|my|your|final|key|pros|cons|verdict|conclusion|"
    r"faqs?|frequently|bottom|summary|overview|specs?|specifications|features|recommended|best|top|related|more|about|"
    r"steps?|tips?|quick|common|buying|pricing|comparison|alternatives?|runner|honorable|also|other|bonus|note|warning)\b", re.I)
PLAIN_QUERY = re.compile(r"[A-Za-z][A-Za-z '&/-]+")
# Link text that only says "go to Amazon". A card's heading may name the product for such a link.
BUTTON_TEXT = re.compile(r"^(check|view|buy|shop|see|get|order|compare|find)\b", re.I)


def heading_name(heading: str) -> str:
    """A product name taken from the heading of the card a link sits in, or "" if it does not read as one."""
    name = short_name(re.sub(r"^\s*(#?\d+[.):]?|[-–•])\s+", "", heading))
    if not 2 <= len(name.split()) <= 9 or HEADING_NOT_PRODUCT.match(name) or re.search(r"\b(listing|alternatives?|options?)\b", name, re.I):
        return ""
    return name


def search_label(link) -> str:
    """What to call an Amazon search link: its own text when that is descriptive, else the search phrase."""
    name = short_name(re.sub(r"\s*\(search\)\s*$", "", link.name, flags=re.I))
    if 2 <= len(name.split()) <= 8:
        return name[0].upper() + name[1:]
    query = " ".join(parse_qs(urlsplit(link.href).query).get("k", [""])[0].split())
    if 2 <= len(query.split()) <= 6 and PLAIN_QUERY.fullmatch(query):
        return query[0].upper() + query[1:]
    return ""


def box(row: Row, blocked: frozenset[str] | set[str] = frozenset()) -> str | None:
    """Return the box <div>, or None when the page links to nothing that can be named.

    Products come first, named by their link text or image alt text, else by the heading of the
    card the link sits in (only when that heading has exactly one product under it). Remaining
    places go to the page's own Amazon searches, labelled as searches. Nothing new is linked."""
    links = row.page.content_links
    under: dict[str, set[str]] = {}
    for link in links:
        if link.kind == "product" and link.heading:
            under.setdefault(link.heading, set()).add(link.asin)
    order, tags, names = [], {}, {}
    for link in links:
        if link.kind != "product" or link.asin in blocked or not link.tag:
            continue
        if link.asin not in tags:
            order.append(link.asin)
            tags[link.asin] = link.tag
        if link.asin not in names:
            name = short_name(link.name)
            if not name and BUTTON_TEXT.match(link.text.strip()) and len(under.get(link.heading, ())) == 1:
                name = heading_name(link.heading)
            if name:
                names[link.asin] = name
    item = '<li style="margin:6px 0"><a href="{url}" rel="sponsored nofollow noopener" target="_blank">{name}</a>{note}</li>'
    items = [item.format(url=html.escape(f"https://www.amazon.com/dp/{asin}?tag={tags[asin]}"), name=html.escape(names[asin]), note="")
             for asin in order if asin in names][:MAX_PRODUCTS]
    products = len(items)
    seen = set()
    for link in links:
        if len(items) == MAX_PRODUCTS:
            break
        label = search_label(link) if link.kind == "search" and link.tag else ""
        if label and label.lower() not in seen:
            seen.add(label.lower())
            items.append(item.format(url=html.escape(link.href), name=html.escape(label), note=' <span style="font-size:13px;color:#555">(Amazon search)</span>'))
    if not items:
        return None
    heading = "Quick links from this guide" if not products else "Quick picks from this guide" if len(items) > 1 else "Featured in this guide"
    return BOX_DIV.format(heading=heading, items="\n".join(items), site=row.site.name)


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
