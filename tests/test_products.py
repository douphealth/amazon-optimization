"""Creators API client, product picker and product box: no network, a fake API instead."""
import json
import re
from pathlib import Path

import pytest

from ace import amazon, fixer, products, transform
from ace.amazon import Creators, Item, parse_item
from ace.config import Config, Site
from ace.page import Link, Page
from ace.score import Row

RAW = {
    "asin": "B014MJ8J2U",
    "detailPageURL": "https://www.amazon.com/dp/B014MJ8J2U?tag=papalex-ph-20&linkCode=ogi&th=1&psc=1",
    "images": {"primary": {"medium": {"url": "https://m.media-amazon.com/images/I/41m._SL160_.jpg", "width": 160, "height": 160},
                           "large": {"url": "https://m.media-amazon.com/images/I/41m._SL500_.jpg", "width": 500, "height": 500}}},
    "itemInfo": {"title": {"displayValue": "XLUX Plant Soil Moisture Meter, for Indoor and Outdoor use"},
                 "byLineInfo": {"brand": {"displayValue": "XLUX"}}, "features": {"displayValues": ["Battery free"]}},
    "offersV2": {"listings": [{"availability": {"type": "IN_STOCK"}, "isBuyBoxWinner": True}]},
    "browseNodeInfo": {"browseNodes": [{"displayName": "Soil Meters"}], "websiteSalesRank": {"salesRank": 87}},
}


def test_parse_item_reads_the_fields_the_box_needs():
    it = parse_item(RAW)
    assert (it.asin, it.brand, it.available, it.buybox, it.sales_rank) == ("B014MJ8J2U", "XLUX", True, True, 87)
    assert it.url.endswith("tag=papalex-ph-20&linkCode=ogi&th=1&psc=1")  # Amazon's link, unchanged
    assert it.image.endswith("_SL160_.jpg") and it.image_w == 160 and it.nodes == ["Soil Meters"]
    gone = parse_item({**RAW, "offersV2": {"listings": [{"availability": {"type": "OUT_OF_STOCK"}}]}})
    assert not gone.available
    assert not parse_item({**RAW, "offersV2": {"listings": []}}).available


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class FakeHTTP:
    """Answers the token endpoint and the API from a script of responses."""

    def __init__(self, api_responses):
        self.api, self.calls, self.tokens = list(api_responses), [], 0

    def post(self, url, json=None, timeout=None, headers=None):
        if "auth/o2/token" in url:
            self.tokens += 1
            assert json["scope"] == "creatorsapi::default" and json["grant_type"] == "client_credentials"
            return Resp(200, {"access_token": f"Atc|{self.tokens}", "expires_in": 3600})
        self.calls.append((url, json, headers))
        return self.api.pop(0)


class Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def client(http, clock, tmp_path=None):
    return Creators("id", "secret", http and "3.1", session=http, clock=clock, sleep=clock.sleep, cache_dir=tmp_path, log=lambda *a: None)


def test_token_is_cached_calls_are_paced_and_throttling_is_retried(tmp_path):
    clock = Clock()
    http = FakeHTTP([Resp(429, {"type": "ThrottleException", "retryAfterSeconds": 3}),
                     Resp(200, {"searchResult": {"items": [RAW]}}),
                     Resp(200, {"searchResult": {"items": []}})])
    c = client(http, clock)
    assert [i.asin for i in c.search("moisture meter", "papalex-ph-20")] == ["B014MJ8J2U"]
    c.search("watering can", "papalex-ph-20")
    assert http.tokens == 1  # one token for all calls
    assert 3 in clock.slept  # retryAfterSeconds honoured
    url, body, headers = http.calls[0]
    assert url == "https://creatorsapi.amazon/catalog/v1/searchItems"
    assert headers["x-marketplace"] == "www.amazon.com" and headers["Authorization"] == "Bearer Atc|1"
    assert body["partnerTag"] == "papalex-ph-20" and body["availability"] == "Available" and "images.primary.medium" in body["resources"]
    starts = [t for t in clock.slept if t < 3]
    assert all(t <= 1.05 for t in starts)  # spaced about a second apart, never a burst


def test_expired_token_is_refreshed_once_and_404_means_no_items():
    clock = Clock()
    http = FakeHTTP([Resp(401, {"type": "UnauthorizedException", "reason": "TokenExpired"}), Resp(404, {"type": "ResourceNotFoundException"})])
    c = client(http, clock)
    assert c.get_items(["B000000000"], "papalex-20") == {}
    assert http.tokens == 2


def test_hard_errors_are_raised_not_swallowed():
    http = FakeHTTP([Resp(400, {"type": "ValidationException", "reason": "InvalidPartnerTag", "message": "Partner tag invalid"})])
    with pytest.raises(amazon.AmazonError, match="InvalidPartnerTag"):
        client(http, Clock()).search("x", "bad-tag")


def test_get_items_batches_ten_per_call_and_caches_a_day(tmp_path):
    clock = Clock()
    asins = [f"B00000000{i}" if i < 10 else f"B0000000{i}" for i in range(12)]
    http = FakeHTTP([Resp(200, {"itemsResult": {"items": [{**RAW, "asin": a} for a in asins[:10]]}}),
                     Resp(200, {"itemsResult": {"items": [{**RAW, "asin": asins[10]}]}})])
    c = client(http, clock, tmp_path)
    got = c.get_items(asins, "papalex-20")
    assert len(http.calls) == 2 and len(http.calls[0][1]["itemIds"]) == 10
    assert set(got) == set(asins[:11])  # the 12th is unknown to Amazon
    assert c.get_items(asins, "papalex-20").keys() == got.keys() and len(http.calls) == 2  # from the cache
    clock.t += 25 * 3600
    http.api = [Resp(200, {"itemsResult": {"items": []}}), Resp(200, {"itemsResult": {"items": []}})]
    assert c.get_items(asins, "papalex-20") == {}  # a day later: asked again


# ---------- picker ----------

def item(asin, title, available=True, image=True, rank=0, buybox=False):
    return Item(asin=asin, title=title, url=f"https://www.amazon.com/dp/{asin}?tag=t-20", image=f"https://m.media-amazon.com/{asin}.jpg" if image else "",
                available=available, sales_rank=rank, buybox=buybox)


class FakeAPI:
    def __init__(self, items=None, searches=None):
        self.items, self.searches, self.calls, self.asked = items or {}, searches or {}, 0, []

    def get_items(self, asins, tag):
        self.asked.append(("get", tuple(asins), tag))
        return {a: self.items[a] for a in asins if a in self.items}

    def search(self, keywords, tag, index="All", count=10):
        self.asked.append(("search", keywords, index, tag))
        if keywords == "boom":
            raise amazon.AmazonError("searchItems: HTTP 400 ValidationException")
        return self.searches.get((keywords, index), self.searches.get(keywords, []))


PLAN = {
    "example.com/monstera-yellow-leaves": products.PlanEntry(
        url="https://example.com/monstera-yellow-leaves/", box=True, topic="monstera care",
        picks=(products.Pick("soil moisture meter", "GardenAndOutdoor", ("moisture", "meter"), ("kids",), "Checks soil moisture before watering"),
               products.Pick("houseplant fertilizer", "All", ("fertilizer",), (), "Feeds the plant during growth"),
               products.Pick("moss pole", "All", ("moss pole",), (), "Gives the vine something to climb"))),
    "example.com/privacy": products.PlanEntry(url="https://example.com/privacy/", box=False),
}


def picker(api, **kw):
    return products.Picker(api, PLAN, image_check=lambda url: True, log=lambda *a: None, **kw)


def test_picker_takes_live_page_products_first_then_fills_from_the_plan():
    api = FakeAPI(items={"B0OWN00001": item("B0OWN00001", "Brand Soil Moisture Meter 3-in-1"),
                         "B0DEAD0001": item("B0DEAD0001", "Old Product", available=False)},
                  searches={("houseplant fertilizer", "All"): [item("B0FERT0001", "Indoor Plant Fertilizer Spikes")],
                            ("moss pole", "All"): [item("B0POLE0001", "Moss Pole for Monstera")]})
    chosen = picker(api).choose("https://example.com/monstera-yellow-leaves/", ["B0DEAD0001", "B0OWN00001"], "papalex-ph-20")
    assert [(p.item.asin, p.source) for p in chosen] == [("B0OWN00001", "page"), ("B0FERT0001", "search"), ("B0POLE0001", "search")]
    assert chosen[0].role == "Checks soil moisture before watering"  # the page's own meter is that pick
    assert not any(a[0] == "search" and a[1] == "soil moisture meter" for a in api.asked)  # type already covered


def test_search_results_must_pass_every_check():
    results = [item("B0KIDS0001", "Kids Moisture Meter Toy"),                 # avoid word
               item("B0NOIM0001", "Soil Moisture Meter", image=False),       # no image
               item("B0OOS00001", "Soil Moisture Meter Pro", available=False),
               item("B0BLOK0001", "Soil Moisture Meter Blocked"),            # blocked ASIN
               item("B0RAIN0001", "Rain Gauge"),                             # wrong product
               item("B0GOOD0001", "Soil Moisture Meter for Plants", rank=500)]
    api = FakeAPI(searches={("soil moisture meter", "GardenAndOutdoor"): results})
    chosen = picker(api, blocked={"B0BLOK0001"}).choose("https://example.com/monstera-yellow-leaves/", [], "t-20")
    assert chosen[0].item.asin == "B0GOOD0001"


def test_ranking_prefers_relevance_then_popularity():
    a, b = item("B0AAAA0001", "Moisture Meter A", rank=900000), item("B0BBBB0001", "Moisture Meter B", rank=50, buybox=True)
    api = FakeAPI(searches={("soil moisture meter", "GardenAndOutdoor"): [a, b]})
    assert picker(api).choose("https://example.com/monstera-yellow-leaves/", [], "t")[0].item.asin == "B0BBBB0001"


def test_failed_search_index_falls_back_to_all_and_no_plan_means_page_products_only():
    api = FakeAPI(searches={("soil moisture meter", "All"): [item("B0GOOD0001", "Soil Moisture Meter")]})
    got = picker(api).choose("https://example.com/monstera-yellow-leaves/", [], "t")
    assert got[0].item.asin == "B0GOOD0001" and ("search", "soil moisture meter", "All", "t") in api.asked
    api2 = FakeAPI(items={"B0OWN00001": item("B0OWN00001", "Whatever")})
    assert [p.source for p in picker(api2).choose("https://example.com/privacy/", ["B0OWN00001"], "t")] == ["page"]
    assert picker(api2).choose("https://example.com/privacy/", [], "t") == []
    assert not any(a[0] == "search" for a in api2.asked)


def test_broken_images_are_skipped():
    api = FakeAPI(searches={("soil moisture meter", "GardenAndOutdoor"): [item("B0BAD00001", "Moisture Meter"), item("B0GOOD0001", "Moisture Meter 2")]})
    pk = products.Picker(api, PLAN, image_check=lambda url: "B0BAD" not in url, log=lambda *a: None)
    assert pk.choose("https://example.com/monstera-yellow-leaves/", [], "t")[0].item.asin == "B0GOOD0001"


def test_display_names_are_short_and_clean():
    cases = {'Mixed Media Sketchbook 9"x12" Multimedia Sketchbook, 60 Sheets': "Mixed Media Sketchbook",
             "TWOHANDS Art Fineliner Ink Pens,Technical Drawing Pen": "TWOHANDS Art Fineliner Ink Pens",
             "Character Development Sheets: 20 Templates": "Character Development Sheets",
             "Victor M154 Metal Pedal Rat Trap - 2 Pack": "Victor M154 Metal Pedal Rat Trap",
             "Worry for Nothing: Guided Anxiety Journal": "Worry for Nothing: Guided Anxiety Journal"}
    for title, want in cases.items():
        assert products.display_name(Item(asin="X", title=title)) == want


# ---------- the box in a post ----------

def chosen_products():
    return [products.Product(item("B0AAAA0001", 'Meter <A> & "B"'), 'Meter <A> & "B"', "Checks <moisture>", "search"),
            products.Product(item("B0BBBB0001", "Fertilizer"), "Fertilizer", "", "search")]


def test_box_html_is_safe_compliant_and_findable():
    box = products.render(chosen_products(), "monstera care", "Plantastic Haven")
    assert "<div" in box and box.count("<div") == 1  # no nested div: the engine can find and replace its own box
    assert 'data-ace-box="2"' in box and 'data-asins="B0AAAA0001,B0BBBB0001"' in box
    assert "Meter &lt;A&gt; &amp; &quot;B&quot;" in box and "Checks &lt;moisture&gt;" in box and "<A>" not in box
    assert box.count('rel="sponsored nofollow noopener"') == 4  # image and button for each product; the name is text
    assert "As an Amazon Associate, Plantastic Haven earns from qualifying purchases." in box
    assert "Helpful picks for Monstera Care" in box
    assert not re.search(r"\$\d|price:", box, re.I)  # never a price
    assert products.box_asins(box) == ["B0AAAA0001", "B0BBBB0001"]
    page_only = products.render([products.Product(item("B0AAAA0001", "Meter"), "Meter", "", "page")], "x", "S")
    assert "Featured in this guide" in page_only


def test_box_goes_in_once_and_is_replaced_in_place():
    post = "<p>" + "Intro words here. " * 10 + "</p>\n<h2>Causes</h2><p>Body.</p>"
    box = products.render(chosen_products(), "monstera care", "S")
    once, n = transform.insert_box(post, box)
    assert n == 1 and once.index("ace-quick-picks") < once.index("<h2>")
    assert transform.insert_box(once, box) == (once, 0)  # never twice
    assert transform.replace_box(once, box) == (once, 0)  # unchanged box: no edit
    newer = products.render(chosen_products()[:1], "monstera care", "S")
    swapped, n = transform.replace_box(once, newer)
    assert n == 1 and swapped.count("ace-quick-picks") == 1 and "B0BBBB0001" not in swapped
    assert swapped.index("ace-quick-picks") == once.index("ace-quick-picks")
    old_text_box = '<div class="ace-quick-picks" style="x"><p>Quick picks</p><ul><li><a href="https://www.amazon.com/dp/B0OLD00001?tag=t">Old</a></li></ul></div>'
    upgraded, n = transform.replace_box(post.replace("</p>", "</p>" + old_text_box, 1), box)
    assert n == 1 and "B0OLD00001" not in upgraded and 'data-ace-box="2"' in upgraded


def test_fixer_plans_boxes_from_the_product_plan_and_builds_them_with_the_picker():
    site = Site(domain="example.com", name="Example", tags=["ex-20"])
    cfg = Config(account_tag_prefix="ex", marketplace="www.amazon.com", sites=[site], auto_fix=["box"], box_min_clicks=0, default_tag="papalex-20")
    api = FakeAPI(searches={("soil moisture meter", "GardenAndOutdoor"): [item("B0GOOD0001", "Soil Moisture Meter")]})
    pk = picker(api)
    rows = [Row(site=site, page=Page(url="https://example.com/monstera-yellow-leaves/", status=200), gsc=None),
            Row(site=site, page=Page(url="https://example.com/privacy/", status=200), gsc=None),
            Row(site=site, page=Page(url="https://example.com/has-box/", status=200, has_box=True), gsc=None)]
    actions = fixer.plan(cfg, rows, picker=pk)
    assert [a.row.page.url for a in actions] == ["https://example.com/monstera-yellow-leaves/", "https://example.com/has-box/"]
    post = "<p>" + "Intro words here. " * 10 + "</p>\n<h2>Causes</h2>"
    new, counts = fixer.transform_post(cfg, actions[0], post, pk)
    assert counts["box_added"] == 1 and "B0GOOD0001" in new and ("search", "soil moisture meter", "GardenAndOutdoor", "ex-20") in api.asked
    nothing = FakeAPI()
    new, counts = fixer.transform_post(cfg, actions[0], post, picker(nothing))
    assert new == post and counts["no_matching_product"] == 1


def test_sites_without_their_own_tag_use_the_default_tag():
    site = Site(domain="example.com", name="Example", tags=[])
    cfg = Config(account_tag_prefix="ex", marketplace="www.amazon.com", sites=[site], auto_fix=["box"], default_tag="papalex-20")
    api = FakeAPI(searches={("soil moisture meter", "GardenAndOutdoor"): [item("B0GOOD0001", "Soil Moisture Meter")]})
    row = Row(site=site, page=Page(url="https://example.com/monstera-yellow-leaves/", status=200), gsc=None)
    fixer.transform_post(cfg, fixer.Action(row=row, fixes=["box"]), "<p>" + "w " * 40 + "</p><h2>x</h2>", picker(api))
    assert ("search", "soil moisture meter", "GardenAndOutdoor", "papalex-20") in api.asked


def test_own_asins_reads_post_bodies_and_pages():
    body = '<a href="https://www.amazon.com/dp/B0AAAA0001?tag=x">a</a> <a href="https://amazon.com/Some-Name/dp/B0BBBB0001/">b</a> <a href="https://www.amazon.com/dp/B0AAAA0001">again</a>'
    assert products.own_asins(body) == ["B0AAAA0001", "B0BBBB0001"]


@pytest.mark.parametrize("title,keywords,must", [
    ("Best Compression Boots of 2026: Top Recovery Boots", "Compression Boots", ("boot",)),
    ("10 Best Running Shoes for Flat Feet in 2026", "Running Shoes for Flat Feet", ("shoe",)),
    ("Top 7 Mouse Traps That Actually Work", "Mouse Traps", ("trap",)),
    ("Theragun Prime Review: Worth It?", "Theragun Prime", ("theragun", "prime")),
    ("Best Lunch Boxes for Kids", "Lunch Boxes for Kids", ("box",)),
    ("How to Water a Monstera", None, None),
    ("Best Time to Run", None, None),
    ("Best Affiliate Programs for Beginners", None, None),
    ("Best Exercises for Lower Back Pain", None, None),
])
def test_unplanned_pages_get_a_plan_only_from_plainly_commercial_titles(title, keywords, must):
    e = products.auto_entry("https://example.com/x/", title)
    assert (e.picks[0].keywords, e.picks[0].must) == (keywords, must) if keywords else e is None


def test_picker_plans_unplanned_pages_from_their_title():
    pk = picker(FakeAPI())
    assert pk.wants_box("https://example.com/new-post/", "Best Dog Harness for French Bulldogs")
    assert not pk.wants_box("https://example.com/other/", "Why French Bulldogs Snore")
    assert not pk.wants_box("https://example.com/privacy/", "Best Privacy Screens")  # a reviewed plan wins


REVIEW_PLAN = {
    "example.com/review/asics-gel-nimbus-27": products.PlanEntry(
        url="https://example.com/review/asics-gel-nimbus-27/", box=True, topic="asics gel-nimbus 27",
        picks=(products.Pick("asics gel nimbus 27", "Shoes", ("nimbus",), (), "The shoe this review covers"),
               products.Pick("running socks", "All", ("sock",), (), "Cushioned socks for long runs"))),
    "example.com/review/best-compression-boots": products.PlanEntry(
        url="https://example.com/review/best-compression-boots/", box=True, topic="compression boots",
        picks=(products.Pick("compression boots", "All", ("compression", "boot"), (), "Recovery"),
               products.Pick("massage gun", "All", ("massage",), (), "Muscle work"))),
}


def test_the_reviewed_product_leads_even_when_the_page_links_others_first():
    api = FakeAPI(items={a: item(a, f"Hoka Clifton {a}") for a in ("B0HOKA0001", "B0HOKA0002", "B0HOKA0003")},
                  searches={("asics gel nimbus 27", "Shoes"): [item("B0NIMB0001", "ASICS Men's Gel-Nimbus 27 Running Shoe")],
                            ("running socks", "All"): [item("B0SOCK0001", "Running Socks 6 Pairs")]})
    pk = products.Picker(api, REVIEW_PLAN, image_check=lambda u: True, log=lambda *a: None)
    got = pk.choose("https://example.com/review/asics-gel-nimbus-27/", ["B0HOKA0001", "B0HOKA0002", "B0HOKA0003"], "t")
    assert [p.item.asin for p in got] == ["B0NIMB0001", "B0SOCK0001", "B0HOKA0001"]


def test_a_best_x_page_keeps_its_own_x_products():
    boots = {a: item(a, f"Air Compression Recovery Boots {a}") for a in ("B0BOOT0001", "B0BOOT0002", "B0BOOT0003")}
    api = FakeAPI(items=boots)
    pk = products.Picker(api, REVIEW_PLAN, image_check=lambda u: True, log=lambda *a: None)
    got = pk.choose("https://example.com/review/best-compression-boots/", list(boots), "t")
    assert [p.item.asin for p in got] == list(boots) and not any(a[0] == "search" for a in api.asked)


@pytest.mark.parametrize("title,brand,want", [
    ("BOOJO 5 Pack Workout Shirts for Men-Quick Dry Black Gym Moisture Wicking", "BOOJO", "BOOJO Workout Shirts for Men"),
    ("Stelle Women 2 in 1 Running Shorts High Waisted Athletic Shorts Gym Workout Shorts with Liner", "Stelle", "Stelle Women 2 in 1 Running Shorts"),
    ("Hoka Men's Clifton 10 Black/White 9 Medium", "HOKA", "Hoka Men's Clifton 10"),
    ("Marcy Fitness Equipment Mat and Floor Protector 3 x 6.5 ft", "Marcy", "Marcy Fitness Equipment Mat and Floor Protector"),
])
def test_names_drop_pack_counts_colours_and_sizes(title, brand, want):
    assert products.display_name(Item(asin="X", title=title, brand=brand)) == want


def test_model_names_with_hyphens_survive():
    assert products.display_name(Item(asin="X", title="ASICS Men's Gel-Nimbus 27 Running Shoe", brand="ASICS")) == "ASICS Men's Gel-Nimbus 27 Running Shoe"


def test_a_rebuilt_box_does_not_count_its_own_products_as_the_articles():
    site = Site(domain="example.com", name="Example", tags=["ex-20"])
    cfg = Config(account_tag_prefix="ex", marketplace="www.amazon.com", sites=[site], auto_fix=["box"], default_tag="papalex-20")
    api = FakeAPI(searches={("soil moisture meter", "GardenAndOutdoor"): [item("B0GOOD0001", "Soil Moisture Meter")]})
    row = Row(site=site, page=Page(url="https://example.com/monstera-yellow-leaves/", status=200, has_box=True), gsc=None)
    old_box = products.render([products.Product(item("B0GOOD0001", "Soil Moisture Meter"), "Soil Moisture Meter", "Checks", "search")], "monstera care", "Example")
    post = "<p>" + "w " * 40 + "</p>" + old_box + "<h2>x</h2>"
    action = fixer.Action(row=row, fixes=["box"])
    fixer.transform_post(cfg, action, post, picker(api))
    assert [p.source for p in action.products][0] == "search"
    assert not any(a[0] == "get" for a in api.asked)  # the box's own product was not treated as the article's
