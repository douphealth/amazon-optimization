"""Choose real Amazon products for a page and render its product box.

Where the products come from, in order:
1. Products the page already links to (its own judgement), confirmed live with the Creators API:
   still sold, has an image. Dead or unsellable ones are dropped.
2. The page's product plan (data/products/plan.json): up to three product types per page, each a
   search phrase plus the words a correct product's title must contain. Amazon is searched, and
   the first results that pass every check are taken: required words present, excluded words
   absent, in stock, has an image, not a blocked ASIN, not already in the box. Among the passing
   results, Amazon's relevance order decides, nudged by sales rank and the buy box.
A page with no confirmed product gets no box. Links are the ones Amazon returns for the site's own
tracking ID, unchanged. Prices are never shown, so a box can never carry a stale price.
"""
from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from .amazon import AmazonError, Creators, Item
from .config import norm_url

PLAN = Path("data/products/plan.json")
REGISTRY = Path("data/products/boxes.json")
MAX_PRODUCTS = 3
BOX_VERSION = "2"
LOOK_AT = 8  # search results considered per product type

DP_LINK = re.compile(r"https?://(?:www\.)?amazon\.com/(?:[^\"'\s<>]*/)?(?:dp|gp/product)/([A-Z0-9]{10})", re.I)


@dataclass
class Pick:
    keywords: str
    index: str = "All"
    must: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    role: str = ""


@dataclass
class PlanEntry:
    url: str
    box: bool
    topic: str = ""
    why: str = ""
    picks: tuple[Pick, ...] = ()


@dataclass
class Product:
    item: Item
    name: str
    role: str
    source: str  # "page" or "search"


def load_plan(path: Path = PLAN) -> dict[str, PlanEntry]:
    if not path.exists():
        return {}
    out = {}
    for key, e in json.loads(path.read_text()).items():
        picks = tuple(Pick(keywords=p["keywords"], index=p.get("index") or "All",
                           must=tuple(m.lower() for m in p.get("must") or ()), avoid=tuple(a.lower() for a in p.get("avoid") or ()),
                           role=p.get("role") or "") for p in e.get("picks") or [])
        out[key] = PlanEntry(url=e.get("url", key), box=bool(e.get("box")), topic=e.get("topic") or "", why=e.get("why") or "", picks=picks)
    return out


def matches(item: Item, pick: Pick, blocked: set[str] | frozenset[str] = frozenset()) -> bool:
    title = item.title.lower()
    return (item.available and bool(item.image) and bool(item.url) and item.asin not in blocked
            and all(m in title for m in pick.must) and not any(a in title for a in pick.avoid))


def rank_key(position: int, item: Item) -> float:
    """Lower is better: Amazon's relevance position first, then popularity and the buy box."""
    popularity = math.log10(item.sales_rank) if item.sales_rank else 6.0
    return position + 0.4 * popularity - (0.5 if item.buybox else 0.0)


CUT = re.compile(r"\s*(?:,|\s[-–—|/]\s|[(\[{]|\s[–—]|;|\||(?:(?<=\bMen)|(?<=\bWomen)|(?<=\bKids)|(?<=\bAdults)|(?<=\bBoys)|(?<=\bGirls)|(?<=\bUnisex))-(?=[A-Z]))")
PACK = re.compile(r"\b(?:\d+\s*-?\s*(?:pack|pcs?|pieces|count|ct)|pack\s+of\s+\d+)\b", re.I)
# A colour pair ("Black/White") or a size or measure starts the end of the name proper.
TAIL = re.compile(r"\s+(?:[A-Za-z]+/[A-Za-z]+\b|\d+(?:\.\d+)?\s*(?:\"|''|inch(?:es)?\b|in\b(?!\s+1\b)|cm\b|mm\b|oz\b|lbs?\b|ml\b|ft\b|feet\b)|\d+(?:\.\d+)?\s*[x×]\s*\d+).*$", re.I)


def display_name(item: Item, limit: int = 60) -> str:
    """A short, clean product name from a marketplace title.

    "Mixed Media Sketchbook 9"x12" Multimedia Sketchbook, 60 Sheets" -> "Mixed Media Sketchbook";
    "Character Development Sheets: 20 Templates..." -> "Character Development Sheets"."""
    title = " ".join(item.title.split())
    name = CUT.split(title, maxsplit=1)[0].strip()
    if ":" in name:
        head, tail = name.split(":", 1)
        if len(head.split()) >= 2 and (len(name) > limit or re.match(r"\s*\d", tail) or len(tail.split()) <= 2):
            name = head
    name = " ".join(PACK.sub(" ", name).split())
    tail = TAIL.search(name)
    if tail and len(name[: tail.start()].split()) >= 3:
        name = name[: tail.start()].strip()
    words, seen = name.split(), {}
    for i, w in enumerate(words):  # "... Sketchbook ... Multimedia Sketchbook": stop at the first repeat
        key = re.sub(r"\W", "", w.lower())
        if len(key) > 3 and key in seen and i - seen[key] > 1:
            words = words[:seen[key] + 1]
            break
        seen.setdefault(key, i)
    name = " ".join(words)
    if len(name) > limit:
        name = name[:limit].rsplit(" ", 1)[0]
    name = re.sub(r"[\s,;:&/|–-]+(with|for|and|or|of|the|to|in|a|an|by|on)?$", "", name, flags=re.I).strip()
    if len(name) < 4:
        name = title[:limit].rsplit(" ", 1)[0]
    if item.brand and len(name.split()) <= 2 and item.brand.lower() not in name.lower():
        name = f"{item.brand} {name}"
    return name


def role_for(item: Item, picks: tuple[Pick, ...]) -> str:
    for pick in picks:
        if pick.must and all(m in item.title.lower() for m in pick.must):
            return pick.role
    return ""


def image_loads(url: str) -> bool:
    """True when Amazon's image server answers the image URL with an image."""
    import requests
    try:
        r = requests.get(url, timeout=15, stream=True)
        ok = r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/")
        r.close()
        return ok
    except requests.RequestException:
        return False


def own_asins(page_or_html) -> list[str]:
    """ASINs a page links to, in order of first appearance (a Page, or a post body as text)."""
    if isinstance(page_or_html, str):
        return list(dict.fromkeys(m.upper() for m in DP_LINK.findall(page_or_html)))
    return list(dict.fromkeys(l.asin.upper() for l in page_or_html.content_links if l.kind == "product" and l.asin))


# Titles that name what readers came to buy. Anything else waits for a reviewed plan entry.
BEST = re.compile(r"^(?:the\s+)?(?:\d+\s+)?(?:best|top(?:\s+\d+)?)\s+(?P<thing>.+?)(?:\s+(?:of|in|for)\s+(?:20\d\d)\b|\s+20\d\d\b|\s*[:(|–—-]|$)", re.I)
REVIEW = re.compile(r"^(?P<thing>.+?)\s+review\b", re.I)
FILLER = re.compile(r"\b(?:20\d\d|reviewed|tested|ranked|guide|picks?|options?|choices?|deals?|budget|cheap|affordable|expert|ultimate|complete)\b", re.I)


# Things a "best ..." title can name that are not products to buy.
NOT_PRODUCTS = set("""time times way ways place places age day days month months year exercise exercises workout workouts
stretch stretches tip tips idea ideas app apps website websites site sites software plugin plugins platform platforms
program programs strategy strategies method methods technique techniques practice practices position positions sport
sports routine routines course courses job jobs career careers niche niches network networks affiliate affiliates
number numbers meaning meanings sign signs prompt prompts tool tools service services""".split())


def stem(word: str) -> str:
    """A substring every singular or plural form contains: boots -> boot, supplies -> suppl, boxes -> box."""
    w = word.lower()
    if w.endswith(("xes", "ches", "shes", "sses", "zes")):
        return w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def auto_entry(url: str, title: str) -> PlanEntry | None:
    """A plan for a page nobody has planned yet, from its title, only when the title plainly names a
    product to buy ("Best Compression Boots of 2026", "Top 10 Running Shoes for Flat Feet",
    "Theragun Prime Review"). Required words: the product noun, so a wrong product cannot pass."""
    m = BEST.match(title.strip()) or REVIEW.match(title.strip())
    if not m:
        return None
    thing = " ".join(FILLER.sub(" ", m.group("thing")).split()).strip(" ,.-")
    thing = re.split(r"\s+(?:that|which|you|to|we|i|actually|worth)\b", thing, maxsplit=1, flags=re.I)[0].strip(" ,.-")
    head = re.split(r"\s+(?:for|with|under|on|in|from|by)\s+", thing, maxsplit=1, flags=re.I)[0]
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", head)
    if not 1 <= len(words) <= 6 or len(thing.split()) > 9 or any(w.lower() in NOT_PRODUCTS for w in words):
        return None
    if m.re is REVIEW:  # a named model: every word of the name must be in the product title
        must = tuple(stem(w) for w in words if len(w) > 1)
    else:
        must = (stem(words[-1]),)
    if not must or len(must[-1]) < 3:
        return None
    return PlanEntry(url=url, box=True, topic=thing.lower()[:60], why="auto: commercial title",
                     picks=(Pick(keywords=thing, index="All", must=must, role=""),))


class Picker:
    def __init__(self, client: Creators, plan: dict[str, PlanEntry] | None = None,
                 blocked: set[str] | frozenset[str] = frozenset(), log=print, image_check=None):
        self.client, self.plan, self.blocked, self.log = client, plan if plan is not None else load_plan(), set(blocked), log
        self.image_check = image_check if image_check is not None else image_loads
        self._images: dict[str, bool] = {}
        self.known: set[str] = set()  # pages whose box is in the registry: the daily refresh keeps those current

    def image_ok(self, url: str) -> bool:
        if url not in self._images:
            self._images[url] = bool(url) and self.image_check(url)
        return self._images[url]

    def entry(self, url: str, title: str = "") -> PlanEntry | None:
        hit = self.plan.get(norm_url(url))
        if hit is None and title:
            hit = auto_entry(url, title)
            if hit:
                self.plan[norm_url(url)] = hit
        return hit

    def wants_box(self, url: str, title: str = "") -> bool:
        e = self.entry(url, title)
        return bool(e and e.box)

    def choose(self, url: str, asins: list[str], tag: str) -> list[Product]:
        """Up to three products, the page's main product type first.

        1. The page's own products of the plan's first (main) type, as many as fit; if the page links
           none that are still sold, the best search result for that type.
        2. One product for each further planned type: the page's own if it has one, else searched.
        3. Any remaining slots: the page's other products, in the order the article links them.
        Without a plan (or a plan saying no box) the box holds the page's own products only."""
        entry = self.entry(url)
        picks = entry.picks if entry and entry.box else ()
        own: list[Product] = []
        if asins:
            wanted = [a for a in dict.fromkeys(asins) if a not in self.blocked][:10]
            found = self.client.get_items(wanted, tag)
            for asin in wanted:
                item = found.get(asin)
                if item and item.available and item.image and item.url and self.image_ok(item.image):
                    own.append(Product(item, display_name(item), role_for(item, picks), "page"))
        fits = lambda p, pick: bool(pick.must) and all(m in p.item.title.lower() for m in pick.must)
        chosen: list[Product] = []
        seen: set[str] = set()

        def add(product: Product) -> None:
            if len(chosen) < MAX_PRODUCTS and product.item.asin not in seen:
                chosen.append(product)
                seen.add(product.item.asin)

        for n, pick in enumerate(picks):
            if len(chosen) == MAX_PRODUCTS:
                break
            mine = [p for p in own if fits(p, pick) and p.item.asin not in seen]
            if mine:
                for product in (mine if n == 0 else mine[:1]):
                    add(product)
                continue
            if any(fits(p, pick) for p in chosen):
                continue  # this product type is already in the box
            best = self._search(pick, tag, seen | {p.item.asin for p in own})
            if best:
                add(Product(best, display_name(best), pick.role, "search"))
        for product in own:
            add(product)
        return chosen

    def _search(self, pick: Pick, tag: str, seen: set[str]) -> Item | None:
        for index in dict.fromkeys([pick.index or "All", "All"]):
            try:
                results = self.client.search(pick.keywords, tag, index=index)
            except AmazonError as exc:
                self.log(f"search '{pick.keywords}' in {index}: {exc}")
                continue
            passing = [(i, it) for i, it in enumerate(results[:LOOK_AT])
                       if it.asin not in seen and matches(it, pick, self.blocked) and self.image_ok(it.image)]
            if passing:
                return min(passing, key=lambda p: rank_key(*p))[1]
        return None

    def box(self, url: str, asins: list[str], tag: str, site_name: str) -> tuple[str, list[Product]]:
        products = self.choose(url, asins, tag)
        if not products:
            return "", []
        entry = self.entry(url)
        return render(products, entry.topic if entry else "", site_name), products


# ---------- the box ----------

LINK = 'href="{url}" rel="sponsored nofollow noopener" target="_blank"'
BOX = (
    '<div class="ace-quick-picks" data-ace-box="{version}" data-asins="{asins}" style="border:1px solid #e5e7eb;'
    'border-radius:12px;background:#fff;padding:16px 16px 12px;margin:22px 0;box-shadow:0 1px 3px rgba(16,24,40,.06)">\n'
    '<p style="margin:0 0 2px;font-size:12px;line-height:1.4;letter-spacing:.06em;text-transform:uppercase;color:#6b7280;font-weight:600">{label}</p>\n'
    '<p style="margin:0 0 6px;font-size:18px;line-height:1.3;font-weight:700;color:#111827">{heading}</p>\n'
    '<ul style="list-style:none;margin:0;padding:0">\n{items}\n</ul>\n'
    '<p style="margin:8px 0 0;font-size:12px;line-height:1.5;color:#6b7280">As an Amazon Associate, {site} earns from qualifying purchases.</p>\n'
    '</div>'
)
ITEM = (
    '<li style="display:flex;gap:14px;align-items:center;margin:0;padding:12px 0;border-top:1px solid #f1f2f4;list-style:none">'
    '<a {link} style="flex:0 0 84px;display:block;line-height:0">'
    '<img src="{img}" width="84" height="84" alt="{alt}" loading="lazy" decoding="async" '
    'style="width:84px;height:84px;max-width:84px;object-fit:contain;border-radius:8px;margin:0;border:0;box-shadow:none"></a>'
    '<span style="flex:1 1 auto;min-width:0;display:block">'
    # The name is plain text: some themes restyle every text link to Amazon as a big button.
    '<span style="display:block;font-size:16px;line-height:1.35;font-weight:700;color:#111827">{name}</span>'
    '{role}'
    '<a {link} style="display:inline-block;margin-top:8px;background:#ff9900;color:#111;font-size:14px;line-height:1;font-weight:700;'
    'padding:10px 14px;border-radius:8px;text-decoration:none">Check price on Amazon</a>'
    '</span></li>'
)
ROLE = '<span style="display:block;margin-top:3px;font-size:14px;line-height:1.45;color:#4b5563">{role}</span>'


SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "with", "your", "from"}


def title_case(text: str) -> str:
    """"asics gel-nimbus 27" -> "Asics Gel-Nimbus 27"; small words stay lower; words already capitalised keep their case."""
    words = text.split()
    out = []
    for i, w in enumerate(words):
        if w != w.lower() or (i and w in SMALL):
            out.append(w)
        else:
            out.append("-".join(part[:1].upper() + part[1:] for part in w.split("-")))
    return " ".join(out)


def render(products: list[Product], topic: str, site_name: str) -> str:
    items = []
    for p in products[:MAX_PRODUCTS]:
        link = LINK.format(url=html.escape(p.item.url, quote=True))
        items.append(ITEM.format(link=link, img=html.escape(p.item.image, quote=True), alt=html.escape(p.name, quote=True),
                                 name=html.escape(p.name), role=ROLE.format(role=html.escape(p.role)) if p.role else ""))
    from_page = all(p.source == "page" for p in products)
    topic = title_case(" ".join(topic.split())[:60])
    label = "Quick picks"
    if from_page:
        heading = "Featured in this guide"
    else:
        heading = f"Helpful picks for {topic}" if topic else "Helpful picks for this guide"
    return BOX.format(version=BOX_VERSION, asins=",".join(p.item.asin for p in products[:MAX_PRODUCTS]),
                      label=label, heading=html.escape(heading), items="\n".join(items), site=html.escape(site_name))


def box_asins(box_html: str) -> list[str]:
    m = re.search(r'data-asins="([A-Z0-9,]*)"', box_html)
    return [a for a in (m.group(1).split(",") if m else []) if a]


def same_box(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


# ---------- registry of live boxes ----------

def load_registry(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_registry(registry: dict, path: Path = REGISTRY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(registry.items())), indent=1, ensure_ascii=False) + "\n")
