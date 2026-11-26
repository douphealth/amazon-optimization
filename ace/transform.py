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

    The search phrase is the link's own text when that is descriptive (so the search matches what
    the reader was promised), else the fallback phrase configured for the product. Image links and
    generic "Shop on Amazon" buttons use the fallback. Returns (html, replaced, left_for_manual_review)."""
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
        query = text if descriptive else blocked[link.asin]
        if not query:
            manual += 1
            return match.group(0)
        replaced += 1
        url = f"https://{marketplace}/s?k={quote_plus(query)}&amp;tag={link.tag or site_tag}"
        return open_tag[: m.start(3)] + url + open_tag[m.end(3):] + inner + close

    return ANCHOR.sub(repl, html), replaced, manual


BLOCK_COMMENT = re.compile(r"<!--\s*(/?)wp:([a-z0-9/-]+)[^>]*?(/?)-->", re.I)
# header, footer and form count too: a box must not land inside an article's hero header.
CONTAINER = re.compile(r"<(/?)(?:div|section|article|aside|nav|header|footer|form|main|table|ul|ol|blockquote|figure|details)\b[^>]*>", re.I)


def _open_block(html: str, at: int) -> str | None:
    """Name of the innermost block-editor block that is still open at position `at`, if any."""
    stack: list[str] = []
    for m in BLOCK_COMMENT.finditer(html, 0, at):
        closing, name, self_closing = m.groups()
        if self_closing:
            continue
        if closing:
            if stack:
                stack.pop()
        else:
            stack.append(name.lower())
    return stack[-1] if stack else None


def _place(html: str, fragment: str, at: int) -> str | None:
    """Insert `fragment` at `at`, respecting the block editor's structure.

    Top level of a block post: wrap in an HTML block. Inside an HTML block, or in a classic
    post: insert as is. Inside any other block: refuse (None), since that would corrupt it."""
    inside = _open_block(html, at)
    if inside not in (None, "html"):
        # Right at the end of a paragraph-like block: step past its closing comment instead.
        closing = re.compile(rf"\s*<!--\s*/wp:{re.escape(inside)}\s*-->", re.I).match(html, at)
        if not closing:
            return None
        at = closing.end()
        inside = _open_block(html, at)
        if inside not in (None, "html"):
            return None
    if inside is None and "<!-- wp:" in html:
        fragment = f"<!-- wp:html -->\n{fragment}\n<!-- /wp:html -->"
    return f"{html[:at].rstrip()}\n\n{fragment}\n\n{html[at:].lstrip()}"


def _depth(html: str, at: int) -> int:
    """How many container elements (div, section, table, list...) are open at position `at`."""
    return sum(-1 if m.group(1) else 1 for m in CONTAINER.finditer(html, 0, at))


CHROME_TAG = re.compile(r"<(/?)(?:header|footer|nav|aside|form)\b[^>]*>", re.I)


RAW_TEXT_TAG = re.compile(r"<(/?)(style|script|textarea|template|noscript)\b[^>]*>", re.I)


def _in_chrome(html: str, at: int) -> bool:
    """True when position `at` is no place for a box: inside a header, footer, nav, aside or form
    (e.g. an article's hero), or inside a <style> or <script> block, where HTML is not rendered.
    Some posts carry a stylesheet with stray </p> tags in it, so this has to be checked."""
    raw_open = ""
    for m in RAW_TEXT_TAG.finditer(html, 0, at):
        if not raw_open and not m.group(1):
            raw_open = m.group(2).lower()
        elif m.group(1) and m.group(2).lower() == raw_open:
            raw_open = ""
    if raw_open:
        return True
    return sum(-1 if m.group(1) else 1 for m in CHROME_TAG.finditer(html, 0, at)) > 0


def add_disclosure(html: str, site_name: str) -> tuple[str, int]:
    """Put the Associates disclosure at the top of a post that has none."""
    if DISCLOSURE.search(html):
        return html, 0
    line = (
        f'<p class="{DISCLOSURE_CLASS}" style="font-size:14px;color:#555;margin:0 0 16px"><em>As an Amazon '
        f"Associate, {htmllib.escape(site_name)} earns from qualifying purchases.</em></p>"
    )
    if "<!-- wp:" in html:
        line = f"<!-- wp:html -->\n{line}\n<!-- /wp:html -->"
    return f"{line}\n\n{html}", 1


GENERATED_BOX = re.compile(
    r"(?:<!-- wp:html -->\s*)?<div class=\"" + BOX_CLASS + r"\"(?:(?!<div\b).)*?</div>\s*(?:<!-- /wp:html -->\s*)?", re.S)


def remove_box(html: str) -> tuple[str, str]:
    """Take a generated box (one with no nested <div>) out of a post. Returns (html, the box div)."""
    m = GENERATED_BOX.search(html)
    if not m:
        return html, ""
    box = re.search(r"<div.*?</div>", m.group(0), re.S).group(0)
    return html[: m.start()].rstrip() + "\n\n" + html[m.end():].lstrip(), box


PLACE_AFTER = re.compile(r"^\s*<!--\s*place-after:\s*(.+?)\s*-->\s*\n", re.I)
MIN_INTRO_WORDS = 30


def insert_box(html: str, box: str) -> tuple[str, int]:
    """Insert a product box near the top of a post.

    A box may start with `<!-- place-after: REGEX -->` to go right after the first match of
    REGEX (hand-written boxes use this). Otherwise it goes after the first intro paragraph that
    is not nested inside a callout, or failing that just before the first H2 when the post has
    an intro. Skipped when no safe place exists or the post already has a box."""
    if BOX_CLASS in html or BOX_CLASS not in box:
        return html, 0
    directive = PLACE_AFTER.match(box)
    if directive:
        spot = re.search(directive.group(1), html, re.I | re.S)
        at = spot.end() if spot else None
        box = box[directive.end():]
    else:
        at = None
        h2 = FIRST_H2.search(html)
        if h2:
            h2_depth = _depth(html, h2.start())
            for p_end in FIRST_P_END.finditer(html, 0, h2.start()):
                if _depth(html, p_end.end()) <= h2_depth and not _in_chrome(html, p_end.end()):
                    at = p_end.end()
                    break
            intro_words = len(re.sub(r"<(style|script)\b.*?</\1>|<[^>]+>", " ", html[: h2.start()], flags=re.S | re.I).split())
            if at is None and intro_words >= MIN_INTRO_WORDS and not _in_chrome(html, h2.start()):
                at = h2.start()
    if at is None:
        return html, 0
    placed = _place(html, box.strip(), at)
    return (placed, 1) if placed is not None else (html, 0)
