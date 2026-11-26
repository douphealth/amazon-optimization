"""Pure, idempotent edits to a post's HTML. No network, no WordPress: text in, text out.

Every function returns (new_html, number_of_changes). Running one twice changes nothing the
second time, so a fix can be re-applied safely.
"""
from __future__ import annotations

import html as htmllib
import re
from urllib.parse import quote_plus

from .page import DISCLOSURE, GENERIC_ANCHOR, classify

A_OPEN = re.compile(r"<a\b[^>]*>", re.I | re.S)
ANCHOR = re.compile(r"(<a\b[^>]*>)(.*?)(</a>)", re.I | re.S)
HREF = re.compile(r"""(\bhref\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
REL = re.compile(r"""(\s+rel\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
TAG_PARAM = re.compile(r"((?:[?&]|&amp;)tag=)[^&#\s\"']*", re.I)
FIRST_H2 = re.compile(r"<h2\b", re.I)
FIRST_P_END = re.compile(r"</p\s*>", re.I)

# Insertions are marked with a class name, not an HTML comment: WordPress wraps stand-alone
# comments in empty paragraphs. The class makes each insertion findable and removable.
BOX_CLASS, DISCLOSURE_CLASS = "ace-quick-picks", "ace-disclosure"


def set_tag(href: str, tag: str) -> str:
    """Set the tracking tag on a raw href attribute value, keeping its & / &amp; style."""
    if TAG_PARAM.search(href):
        return TAG_PARAM.sub(lambda m: m.group(1) + tag, href, count=1)
    base, hash_sep, fragment = href.partition("#")
    amp = "&" if re.search(r"&(?!amp;)", base) else "&amp;"
    joiner = "" if base.endswith(("?", "&", "&amp;")) else (amp if "?" in base else "?")
    return f"{base}{joiner}tag={tag}{hash_sep}{fragment}"


def _amazon_link(open_tag: str, allow_short: bool = False):
    """Return (href match, Link) if the <a ...> tag points at Amazon, else None.
    amzn.to short links only count when allow_short is set: their tag cannot be read or edited."""
    m = HREF.search(open_tag)
    if not m:
        return None
    link = classify(htmllib.unescape(m.group(3)))
    if link is None or (link.kind == "short" and not allow_short):
        return None
    return m, link


def fix_tags(html: str, site_tag: str, allowed: list[str], prefix: str) -> tuple[str, int]:
    """Add the site's tracking ID to untagged Amazon links, and replace other IDs from the same
    Associates account. Tags that do not start with `prefix` belong to someone else: left alone."""
    changes = 0

    def repl(match: re.Match) -> str:
        nonlocal changes
        tag = match.group(0)
        found = _amazon_link(tag)
        if not found:
            return tag
        m, link = found
        wrong = link.tag and link.tag.startswith(prefix) and link.tag not in allowed
        if link.tag and not wrong:
            return tag
        changes += 1
        return tag[: m.start(3)] + set_tag(m.group(3), site_tag) + tag[m.end(3):]

    return A_OPEN.sub(repl, html), changes


def fix_rel(html: str) -> tuple[str, int]:
    """Give Amazon links rel="sponsored nofollow" when they have neither."""
    changes = 0

    def repl(match: re.Match) -> str:
        nonlocal changes
        tag = match.group(0)
        if not _amazon_link(tag, allow_short=True):
            return tag
        rel = REL.search(tag)
        values = rel.group(3).split() if rel else []
        if {"sponsored", "nofollow"} & {v.lower() for v in values}:
            return tag
        changes += 1
        if rel:
            merged = " ".join(values + ["sponsored", "nofollow"])
            return tag[: rel.start(3)] + merged + tag[rel.end(3):]
        return tag[:-1].rstrip() + ' rel="sponsored nofollow noopener">'

    return A_OPEN.sub(repl, html), changes


def replace_blocked(
    html: str, blocked: dict[str, str | None], marketplace: str, site_tag: str,
) -> tuple[str, int, int]:
    """Point links to blocked products at an Amazon search instead.

    The search phrase is the one configured for that product, else the link's own text when it
    is descriptive. Returns (html, replaced, left_for_manual_review)."""
    replaced = manual = 0

    def repl(match: re.Match) -> str:
        nonlocal replaced, manual
        open_tag, inner, close = match.groups()
        found = _amazon_link(open_tag)
        if not found or found[1].asin not in blocked:
            return match.group(0)
        m, link = found
        text = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", inner)).split())
        descriptive = len(text.split()) >= 2 and len(text) <= 80 and not GENERIC_ANCHOR.match(text)
        query = blocked[link.asin] or (text if descriptive else None)
        if not query:
            manual += 1
            return match.group(0)
        replaced += 1
        url = f"https://{marketplace}/s?k={quote_plus(query)}&amp;tag={link.tag or site_tag}"
        return open_tag[: m.start(3)] + url + open_tag[m.end(3):] + inner + close

    return ANCHOR.sub(repl, html), replaced, manual


def _wrap(html: str, fragment: str) -> str:
    """Block-editor posts need raw HTML inside an HTML block."""
    return f"<!-- wp:html -->\n{fragment}\n<!-- /wp:html -->" if "<!-- wp:" in html else fragment


def add_disclosure(html: str, site_name: str) -> tuple[str, int]:
    """Put the Associates disclosure at the top of a post that has none."""
    if DISCLOSURE.search(html):
        return html, 0
    line = (
        f'<p class="{DISCLOSURE_CLASS}" style="font-size:14px;color:#555;margin:0 0 16px"><em>As an Amazon '
        f"Associate, {htmllib.escape(site_name)} earns from qualifying purchases.</em></p>"
    )
    return f"{_wrap(html, line)}\n\n{html}", 1


def insert_box(html: str, box: str) -> tuple[str, int]:
    """Insert a product box after the opening paragraph (or before the first H2).
    Skipped when the post has neither, or already has a box."""
    if BOX_CLASS in html or BOX_CLASS not in box:
        return html, 0
    h2 = FIRST_H2.search(html)
    limit = h2.start() if h2 else len(html)
    p_end = FIRST_P_END.search(html, 0, limit)
    if p_end:
        at = p_end.end()
    elif h2:
        at = h2.start()
    else:
        return html, 0
    fragment = _wrap(html, box.strip())
    return f"{html[:at].rstrip()}\n\n{fragment}\n\n{html[at:].lstrip()}", 1
