import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ace import data, fixes, gsc, score
from ace.config import Config, Site, norm_url
from ace.page import classify, parse

SITE = Site(domain="example.com", name="Example", tags=["papalex-ex-20"])
CFG = Config(account_tag_prefix="papalex", marketplace="www.amazon.com", sites=[SITE])

FILLER = "<p>" + "word " * 200 + "</p>"
HTML = f"""<html><head><title>Best Grow Lights  Review</title>
<meta name="description" content="A test page."><link rel="canonical" href="https://example.com/best-grow-lights/">
</head><body><nav><a href="https://www.amazon.com/dp/B000000001?tag=papalex-ex-20">nav link</a> menu menu</nav>
<article><h1>Best Grow Lights</h1>{FILLER}{FILLER}{FILLER}
<a href="https://www.amazon.com/dp/B0CZPPGMWN?tag=papalex-ex-20" rel="sponsored nofollow"><img alt="Molly's Potting Mix, 3 Quarts" src="https://m.media-amazon.com/x.jpg"></a>
<a href="https://www.amazon.com/dp/B0CZPPGMWN?tag=papalex-ex-20" rel="sponsored">Shop on Amazon</a>
<a href="https://www.amazon.com/dp/B085CDPSMR/?tag=papalex-ex-20" rel="sponsored">GooingTop grow light</a>
<a href="https://www.amazon.com/s?k=perlite&tag=other-20">perlite</a>
<a href="https://amzn.to/abc123">short</a>
<a href="https://www.amazon.com/dp/B000000002">untagged</a>
{FILLER}<p>As an Amazon Associate we earn from qualifying purchases.</p></article>
<footer>footer text</footer></body></html>"""


def test_classify_amazon_links():
    assert classify("https://www.amazon.com/dp/B0CZPPGMWN?tag=x-20").asin == "B0CZPPGMWN"
    assert classify("https://www.amazon.co.uk/Some-Name/dp/B0CZPPGMWN/ref=x?tag=y-21").tag == "y-21"
    assert classify("https://www.amazon.com/s?k=perlite&tag=x-20").kind == "search"
    assert classify("https://amzn.to/3abc").kind == "short"
    assert classify("https://aws.amazon.com/s3/") is None
    assert classify("https://m.media-amazon.com/images/I/x.jpg") is None
    assert classify("https://example.com/dp/B0CZPPGMWN") is None


def test_parse_page():
    page = parse("https://example.com/best-grow-lights/", HTML)
    assert page.title == "Best Grow Lights Review"
    assert page.h1 == "Best Grow Lights"
    assert page.meta_description == "A test page."
    assert page.disclosure and page.commercial and not page.noindex
    assert page.amazon_images == 1
    assert len(page.links) == 7 and len(page.content_links) == 6  # nav link is site chrome
    assert 0.70 < page.first_link_depth < 0.80  # after 3 of 4 filler blocks
    assert page.content_links[0].name == "Molly's Potting Mix, 3 Quarts"  # image alt
    assert page.content_links[1].name == ""  # generic "Shop on Amazon" anchor, no alt


def test_parse_recovers_from_unclosed_nav():
    html = "<html><body><nav>menu" + FILLER + '<a href="https://www.amazon.com/dp/B0CZPPGMWN?tag=a-20">x</a></body></html>'
    page = parse("https://example.com/x/", html)
    assert page.words > 150 and len(page.content_links) == 1


def test_issues_and_score():
    page = parse("https://example.com/best-grow-lights/", HTML)
    page.status = 200
    issues, gap = score.page_issues(page, SITE, CFG)
    assert gap == score.GAP_VERY_LATE
    for code in ("first_link_very_late", "untagged_link", "foreign_tag", "short_link", "missing_rel_sponsored"):
        assert code in issues
    assert "no_disclosure" not in issues and "other_site_tag" not in issues
    gsc_rows = {norm_url(page.url): data.GscRow(clicks=0, impressions=1000, position=4.2)}
    row = score.build_rows(CFG, {"example.com": [page]}, {"example.com": gsc_rows}, {})[0]
    assert row.reachable_clicks == 80  # 1000 impressions x 8% at position 4
    assert row.score == 56.0 and "low_serp_ctr" in row.issues  # 80 x 0.7


def test_value_weight_uses_associates_epc():
    page = parse("https://example.com/best-grow-lights/", HTML)
    page.status = 200
    other = Site(domain="b.com", name="B", tags=["papalex-b-20"])
    cfg = Config("papalex", "www.amazon.com", [SITE, other])
    stats = {"papalex-ex-20": data.TagStats(100, 5, 9.0), "papalex-b-20": data.TagStats(100, 5, 1.0)}
    gsc_rows = {norm_url(page.url): data.GscRow(10, 1000, 4.2)}
    row = score.build_rows(cfg, {"example.com": [page]}, {"example.com": gsc_rows}, stats)[0]
    assert row.score == round(80 * 0.7 * 1.8, 2)  # EPC 0.09 vs portfolio average 0.05


def test_fix_draft_reuses_page_products():
    page = parse("https://example.com/best-grow-lights/", HTML)
    page.status = 200
    row = score.build_rows(CFG, {"example.com": [page]}, {}, {})[0]
    box = fixes.draft(row)
    assert "https://www.amazon.com/dp/B0CZPPGMWN?tag=papalex-ex-20" in box
    assert ">Molly&#x27;s Potting Mix<" in box and ">GooingTop grow light<" in box
    assert "B000000002" not in box  # untagged product is never promoted
    assert "Example earns from qualifying purchases" in box
    assert "B085CDPSMR" not in (fixes.draft(row, blocked={"B085CDPSMR"}) or "")


def test_blocked_product_is_flagged():
    page = parse("https://example.com/best-grow-lights/", HTML)
    page.status = 200
    cfg = Config("papalex", "www.amazon.com", [SITE], blocked_asins={"B085CDPSMR"})
    assert "blocked_product" in score.page_issues(page, SITE, cfg)[0]
    assert "blocked_product" not in score.page_issues(page, SITE, CFG)[0]


def test_load_gsc_accepts_ui_export_and_drops_fragments(tmp_path):
    folder = tmp_path / "example.com"
    folder.mkdir()
    (folder / "pages.csv").write_text(
        "Top pages,Clicks,Impressions,CTR,Position\n"
        "https://www.example.com/a/,5,\"1,200\",0.4%,7.3\n"
        "https://www.example.com/a/#section,0,300,0%,5\n"
    )
    rows, _ = data.load_gsc("example.com", tmp_path)
    assert list(rows) == ["example.com/a"]
    assert rows["example.com/a"].impressions == 1200 and rows["example.com/a"].position == 7.3


def test_load_associates_finds_header_and_sums(tmp_path):
    (tmp_path / "report.csv").write_text(
        "Fee-Tracking report 2026-11-01 to 2026-11-25\n"
        "Tracking Id,Clicks,Items Ordered,Items Shipped,Total Earnings\n"
        "papalex-ph-20,300,10,9,$4.50\npapalex-gutf-20,100,4,4,$6.00\n"
    )
    stats = data.load_associates(tmp_path)
    assert stats["papalex-ph-20"].epc == 0.015 and stats["papalex-gutf-20"].items == 4


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.ok, self.text = body, status, status < 400, json.dumps(body)
    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)
    def json(self):
        return self.body


def test_gsc_pull_writes_pages_queries_daily_and_resolves_property(tmp_path):
    class Session:
        calls = []
        def get(self, url, timeout):
            return _Resp({"siteEntry": [{"siteUrl": "https://example.com/", "permissionLevel": "siteFullUser"}]})
        def post(self, url, json, timeout):
            self.calls.append((url, json))
            dims = json["dimensions"]
            if dims == ["page"]:
                return _Resp({"rows": [{"keys": ["https://example.com/a/"], "clicks": 3, "impressions": 90, "position": 6.5}]})
            if dims == ["page", "query"]:
                rows = [{"keys": ["https://example.com/a/", f"q{i}"], "clicks": i % 3, "impressions": 10 + i, "position": 5} for i in range(15)]
                return _Resp({"rows": rows})
            return _Resp({"rows": [{"keys": ["2026-11-20"], "clicks": 1, "impressions": 9, "position": 7}]})

    session, logs = Session(), []
    site = Site(domain="example.com", name="Example", gsc_property="sc-domain:example.com")  # not visible: falls back
    used = gsc.pull([site], days=28, root=tmp_path, session=session, today=date(2026, 11, 25), log=logs.append)
    assert used == {"example.com": "https://example.com/"} and any("cannot see" in l for l in logs)
    url, body = session.calls[0]
    assert "https%3A%2F%2Fexample.com%2F" in url and body["startDate"] == "2026-10-26" and body["endDate"] == "2026-11-22"
    rows, meta = data.load_gsc("example.com", tmp_path)
    assert rows["example.com/a"].clicks == 3 and meta["end"] == "2026-11-22" and meta["property"] == "https://example.com/"
    queries = (tmp_path / "example.com" / "queries.csv").read_text().splitlines()
    assert len(queries) == 1 + gsc.QUERIES_PER_PAGE and queries[1].startswith("https://example.com/a/,q14,2")  # most clicks first
    assert (tmp_path / "example.com" / "daily.csv").read_text().splitlines()[1].startswith("2026-11-20,1,9")


def test_gsc_inspect_records_verdicts_and_skips_fresh_pages(tmp_path):
    class Session:
        posts = []
        def get(self, url, timeout):
            return _Resp({"siteEntry": [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteFullUser"}]})
        def post(self, url, json, timeout):
            self.posts.append(json["inspectionUrl"])
            ok = json["inspectionUrl"].endswith("/a/")
            return _Resp({"inspectionResult": {"indexStatusResult": {
                "verdict": "PASS" if ok else "NEUTRAL",
                "coverageState": "Submitted and indexed" if ok else "Crawled - currently not indexed",
                "googleCanonical": json["inspectionUrl"], "lastCrawlTime": "2026-11-20T10:00:00Z"}}})

    session = Session()
    site = Site(domain="example.com", name="Example", gsc_property="sc-domain:example.com")
    urls = ["https://example.com/a/", "https://example.com/b/"]
    done = gsc.inspect([(site, urls)], root=tmp_path, session_factory=lambda: session, today=date(2026, 11, 25), log=lambda *_: None)
    assert done == {"example.com": 2}
    index = gsc.load_index("example.com", tmp_path)
    assert index["example.com/a"]["verdict"] == "PASS" and index["example.com/b"]["coverage"] == "Crawled - currently not indexed"
    assert index["example.com/a"]["last_crawl"] == "2026-11-20"
    session.posts.clear()
    gsc.inspect([(site, urls)], root=tmp_path, session_factory=lambda: session, today=date(2026, 11, 28), log=lambda *_: None)
    assert session.posts == []  # both inspected within the refresh window
    gsc.inspect([(site, urls)], root=tmp_path, session_factory=lambda: session, today=date(2026, 12, 3), log=lambda *_: None)
    assert sorted(session.posts) == urls


def test_bing_pull_aggregates_last_weeks_and_survives_throttling(tmp_path):
    from ace import bing
    ms = lambda d: f"/Date({int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)})/"
    weeks = [date(2026, 10, 16) + timedelta(days=7 * i) for i in range(6)]  # week-ending Fridays, last 2026-11-20

    def page(d, url, clicks, impr, pos):
        return {"Date": ms(d), "Query": url, "Clicks": clicks, "Impressions": impr, "AvgImpressionPosition": pos, "AvgClickPosition": -1}

    answers = {
        "GetUserSites": [{"Url": "https://example.com/", "IsVerified": True}, {"Url": "https://other.com/", "IsVerified": True}],
        # A different click count every day, so a window shifted by even one day gives another total.
        "GetRankAndTrafficStats": [{"Date": ms(date(2026, 10, 14) + timedelta(days=i)), "Clicks": i, "Impressions": 20} for i in range(43)],
        "GetPageStats": [page(w, "https://www.example.com/a/", 5, 100, 4) for w in weeks] + [page(weeks[-1], "https://example.com/b/", 1, 50, 10)],
        "GetQueryStats": [page(w, "widget", 3, 40, 6) for w in weeks],
        "GetCrawlStats": [{"Date": ms(date(2026, 11, 26)), "CrawledPages": 9, "InIndex": 70, "Code4xx": 1}],
        "GetCrawlIssues": [{"Url": "https://example.com/gone/", "HttpCode": 404, "Issues": 4, "InLinks": 2},
                           {"Url": "http://example.com/", "HttpCode": 301, "Issues": 1, "InLinks": 0}],
    }
    calls = []

    class Session:
        def get(self, url, params, timeout):
            method = url.rsplit("/", 1)[-1]
            calls.append(method)
            if method == "GetPageQueryStats":
                if params["page"].endswith("/b/"):
                    return _Resp({"ErrorCode": 4, "Message": "ERROR!!! ThrottleUser"}, status=400)
                return _Resp({"d": [page(weeks[-1], "widget review", 2, 30, 3), page(weeks[0], "too old", 9, 99, 1)]})
            return _Resp({"d": answers[method]})

    client = bing.Client(key="k", session=Session(), pause=0, sleep=lambda s: None)
    logs = []
    out = bing.pull([Site(domain="example.com", name="Example")], root=tmp_path, client=client, today=date(2026, 11, 27), log=logs.append)
    meta = out["example.com"]
    # The four newest buckets are dated 10-30 .. 11-20; a bucket dated D covers D-7 .. D-1.
    assert (meta["start"], meta["end"], meta["weeks"]) == ("2026-10-23", "2026-11-19", 4)
    first = (date(2026, 10, 23) - date(2026, 10, 14)).days
    assert meta["site_clicks_in_window"] == sum(range(first, first + 28)) and meta["page_clicks_in_window"] == 21
    pages, _ = data.load_bing("example.com", tmp_path)
    assert pages["example.com/a"].clicks == 20 and pages["example.com/a"].impressions == 400 and pages["example.com/a"].position == 4
    assert pages["example.com/b"].position == 10
    pq = (tmp_path / "example.com" / "page_queries.csv").read_text()
    assert "widget review,2,30,3" in pq and "too old" not in pq
    assert any("throttled" in l for l in logs)  # one page throttled: kept what it had, no crash
    errors = bing.load_crawl_errors("example.com", tmp_path)
    assert list(errors) == ["example.com/gone"] and errors["example.com/gone"]["issues"] == "4xx"  # the 301 is not an error
    assert bing.decode_issues(4 | 16) == ["4xx", "blocked_by_robots"]
    assert bing.resolve_site(Site(domain="www.other.com", name="O"), ["https://other.com/"]) == "https://other.com/"


def test_ga4_pull_uses_first_property_with_visits(tmp_path):
    from ace import ga4

    class Session:
        def get(self, url, params=None, timeout=None):  # the account can read no property with the site's live tag
            return _Resp({"accountSummaries": []})
        def post(self, url, json, timeout):
            if "111" in url:
                return _Resp({"error": "denied"}, status=403)
            dims = [d["name"] for d in json.get("dimensions", [])]
            if "222" in url:
                return _Resp({"rows": [], "rowCount": 0})
            if not dims:  # totals: GA4's own, which need not equal the sum of rows
                rows = [["9", "6"]] if "Organic Search" in __import__("json").dumps(json.get("dimensionFilter")) else [["50", "9"]]
            elif dims == ["landingPage"]:
                rows = [["/a", "5", "3"], ["/a/", "2", "1"], ["(not set)", "4", "0"]]
            elif dims == ["pagePath"]:
                rows = [["/a/", "7"]]
            elif dims == ["sessionSource", "sessionMedium", "sessionDefaultChannelGroup"]:
                rows = [["bing", "organic", "Organic Search", "9", "6"], ["(direct)", "(none)", "Direct", "40", "2"]]
            else:
                rows = [["20261120", "Organic Search", "3", "2"], ["20261120", "Direct", "10", "1"]]
            n = len(dims)
            return _Resp({"rows": [{"dimensionValues": [{"value": v} for v in r[:n]], "metricValues": [{"value": v} for v in r[n:]]} for r in rows],
                          "rowCount": len(rows)})

    site = Site(domain="example.com", name="Example", ga4_properties=["111", "222", "333"])
    page = lambda url, **kw: type("P", (), {"text": "<script src='https://www.googletagmanager.com/gtag/js?id=G-NOTMINE1'></script>"})()
    out = ga4.pull([site], root=tmp_path, session=Session(), today=date(2026, 11, 27), log=lambda *_: None, get=page)
    meta = out["example.com"]
    assert meta["property"] == "333" and meta["sessions"] == 50 and meta["organic_sessions"] == 9 and meta["amazon_clicks"] == 7
    assert (meta["start"], meta["end"]) == ("2026-10-29", "2026-11-25")  # ends two days back: GA4 is still processing yesterday
    assert any("no access to property 111" in n for n in meta["notes"]) and any("222 recorded no visits" in n for n in meta["notes"])
    visits = data.load_ga4("example.com", tmp_path)
    assert visits["example.com/a"]["sessions"] == 7 and visits["example.com/a"]["amazon_clicks"] == 7
    daily = (tmp_path / "example.com" / "daily.csv").read_text().splitlines()
    assert daily[1] == "2026-11-20,13,3,3"
    assert meta["unreadable_tags"] == ["G-NOTMINE1"] and any("G-NOTMINE1" in n for n in meta["notes"])


def test_ga4_follows_the_live_tag_and_health_names_the_cause(tmp_path):
    from ace import ga4, site as dash

    class Session:
        def get(self, url, params=None, timeout=None):
            if url.endswith("accountSummaries"):
                return _Resp({"accountSummaries": [{"propertySummaries": [{"property": "properties/777"}, {"property": "properties/333"}]}]})
            pid = url.split("/properties/")[1].split("/")[0]
            return _Resp({"dataStreams": [{"webStreamData": {"measurementId": "G-LIVE7777" if pid == "777" else "G-OLD33333"}}]})
        def post(self, url, json, timeout):
            n = len(json.get("dimensions", []))
            rows = [["12", "4"]] if "777" in url and not n else []
            return _Resp({"rows": [{"dimensionValues": [{"value": v} for v in r[:n]], "metricValues": [{"value": v} for v in r[n:]]} for r in rows],
                          "rowCount": len(rows)})

    page = lambda url, **kw: type("P", (), {"text": "gtag('config', 'G-LIVE7777');"})()
    site = Site(domain="example.com", name="Example", ga4_properties=["333"])  # sites.yaml names the old property
    meta = ga4.pull([site], root=tmp_path, session=Session(), today=date(2026, 11, 27), log=lambda *_: None, get=page)["example.com"]
    assert meta["property"] == "777" and meta["sessions"] == 12 and meta["unreadable_tags"] == []
    assert dash.ga_health({"sessions": 0, "tags": {"checked": True, "ga": [], "gtm": []}}, 50)["title"] == "No Analytics tag on the site"
    assert dash.ga_health({"sessions": 3509, "organic_sessions": 170, "tags": {"checked": True, "ga": [], "gtm": []}}, 50) is None  # tag hidden from HTML but working
    wrong = dash.ga_health({"sessions": 0, "tags": {"checked": True, "ga": ["G-X1234567"], "gtm": []}, "unreadable_tags": ["G-X1234567"]}, 50, "sa@x.iam")
    assert wrong["title"] == "Analytics reads the wrong property" and "G-X1234567" in wrong["detail"] and "sa@x.iam" in wrong["detail"]


def _page(url, text, title="T", status=200):
    from ace.page import Page, sketch
    words = text.split()
    return Page(url=url, status=status, final_url=url, title=title, words=len(words),
                text_len=len(text), sketch=sketch(words), meta_description="d")


def test_near_duplicates_and_content_checks():
    import random
    from ace import dupes
    rng = random.Random(1)
    vocab = [f"w{i}" for i in range(4000)]
    template = " ".join(rng.choices(vocab, k=600))
    a = _page("https://example.com/watch/a", template + " " + " ".join(rng.choices(vocab, k=60)), "A")
    b = _page("https://example.com/watch/b", template + " " + " ".join(rng.choices(vocab, k=60)), "B")
    c = _page("https://example.com/unique", " ".join(rng.choices(vocab, k=660)), "A")
    thin = _page("https://example.com/thin", "only a few words here", "Thin")
    assert dupes.similarity(a.sketch, b.sketch) > 0.6 > 0.2 > dupes.similarity(a.sketch, c.sketch)
    assert dupes.clusters([a, b, c, thin]) == {a.url: 2, b.url: 2}
    rows = {r.page.url: r for r in score.build_rows(CFG, {"example.com": [a, b, c, thin]}, {}, {})}
    assert "near_duplicate" in rows[a.url].issues and rows[a.url].cluster_size == 2
    assert "near_duplicate" not in rows[c.url].issues
    assert "duplicate_title" in rows[a.url].issues and "duplicate_title" in rows[c.url].issues
    assert "thin_content" in rows[thin.url].issues and "thin_content" not in rows[a.url].issues


def test_redirect_is_flagged():
    page = _page("https://example.com/old/", "word " * 400)
    page.final_url = "https://example.com/new/"
    assert "redirects" in score.page_issues(page, SITE, CFG)[0]


def test_unclosed_anchor_is_kept():
    html = "<html><body><article>" + FILLER + '<a href="https://www.amazon.com/dp/B0CZPPGMWN?tag=a-20">one <a href="https://www.amazon.com/dp/B085CDPSMR?tag=a-20">two</article></body></html>'
    assert [l.asin for l in parse("https://example.com/x/", html).links] == ["B0CZPPGMWN", "B085CDPSMR"]


def test_sitemap_discovery_resolves_relative_and_follows_index(monkeypatch):
    from ace import crawl

    class R:
        def __init__(self, text, ok=True):
            self.text, self.ok = text, ok

    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    web = {
        "https://example.com/robots.txt": R("User-agent: *\nSitemap: /sitemap_index.xml\n"),
        "https://example.com/sitemap_index.xml": R(
            f"<sitemapindex {ns}><sitemap><loc>https://example.com/post-sitemap.xml</loc></sitemap>"
            f"<sitemap><loc>https://example.com/category-sitemap.xml</loc></sitemap></sitemapindex>"),
        "https://example.com/post-sitemap.xml": R(
            f"<urlset {ns}><url><loc>https://example.com/a/</loc><lastmod>2026-01-01</lastmod></url>"
            f"<url><loc> https://example.com/b/ </loc></url></urlset>"),
    }
    fetched = []
    monkeypatch.setattr(crawl, "fetch", lambda url, ua: (fetched.append(url), web.get(url, R("", ok=False)))[1])
    site = Site(domain="example.com", name="Example", skip_sitemaps="category-sitemap")
    found = crawl.discover(site)
    assert list(found) == ["https://example.com/a/", "https://example.com/b/"]
    assert "https://example.com/category-sitemap.xml" not in fetched


def test_changes_section(tmp_path):
    from ace import changes
    from ace.report import ISSUE_TEXT
    prev, out = tmp_path / "2026-11-01", tmp_path / "2026-11-08"
    prev.mkdir()
    (prev / "pages.csv").write_text(
        "site,url,amazon_links,issues\n"
        "example.com,https://example.com/a/,3,first_link_very_late\n"
        "example.com,https://example.com/b/,2,\n")
    (tmp_path / "notes").mkdir()
    assert changes.previous_report(out) == prev
    a = _page("https://example.com/a/", "word " * 400)  # no Amazon links any more
    rows = score.build_rows(CFG, {"example.com": [a]}, {}, {})
    text = "\n".join(changes.section(prev, rows, sorted(ISSUE_TEXT), ISSUE_TEXT))
    assert "| example.com | no Amazon link in the article | 0 | 1 | +1 |" in text
    assert "| example.com | first Amazon link is in the bottom half | 1 | 0 | -1 |" in text
    assert "- https://example.com/a/" in text and "https://example.com/b/" not in text
    assert "Not compared" in text and "under 300 words" in text  # old report had no thin check


# ---- fixer ----------------------------------------------------------------------------------

def test_set_tag_keeps_ampersand_style():
    from ace.transform import set_tag
    assert set_tag("https://www.amazon.com/dp/B0CZPPGMWN", "x-20") == "https://www.amazon.com/dp/B0CZPPGMWN?tag=x-20"
    assert set_tag("https://www.amazon.com/dp/B0CZPPGMWN?th=1", "x-20").endswith("?th=1&amp;tag=x-20")
    assert set_tag("https://www.amazon.com/s?k=a&ref=b", "x-20").endswith("&ref=b&tag=x-20")
    assert set_tag("https://www.amazon.com/dp/B0CZPPGMWN?tag=old-20&amp;th=1#x", "x-20") == "https://www.amazon.com/dp/B0CZPPGMWN?tag=x-20&amp;th=1#x"


RAW = (
    '<p>Intro paragraph.</p>\n<h2>Soil</h2>\n'
    '<p><a href="https://www.amazon.com/dp/B000000002">untagged</a> '
    '<a class="btn" href="https://www.amazon.com/dp/B0CZPPGMWN?tag=papalex-20" rel="noopener">main id</a> '
    '<a href="https://www.amazon.com/dp/B085CDPSMR?tag=papalex-ex-20" rel="sponsored">fine</a> '
    '<a href="https://www.amazon.com/dp/B000000003?tag=someoneelse-20" rel="nofollow">foreign</a> '
    '<a href="https://amzn.to/abc">short</a> <a href="https://example.com/x">internal</a> '
    '<a href="https://www.amazon.com/dp/B084KRDD5F?tag=papalex-ex-20" rel="sponsored">All-purpose potting mix</a> '
    '<a href="https://www.amazon.com/dp/B084KRDD5F?tag=papalex-ex-20" rel="sponsored">Shop on Amazon</a></p>'
)


def test_transforms_are_precise_and_idempotent():
    from ace import transform as t
    out, n = t.fix_tags(RAW, "papalex-ex-20", ["papalex-ex-20"], "papalex")
    assert n == 2
    assert 'href="https://www.amazon.com/dp/B000000002?tag=papalex-ex-20"' in out
    assert 'class="btn" href="https://www.amazon.com/dp/B0CZPPGMWN?tag=papalex-ex-20" rel="noopener"' in out
    assert "someoneelse-20" in out and 'href="https://amzn.to/abc"' in out  # foreign and short links untouched
    assert t.fix_tags(out, "papalex-ex-20", ["papalex-ex-20"], "papalex") == (out, 0)

    out2, n = t.fix_rel(out)
    assert n == 3  # the untagged one (no rel), the rel="noopener" one, and the amzn.to short link
    assert 'rel="noopener sponsored nofollow"' in out2 and 'B000000002?tag=papalex-ex-20" rel="sponsored nofollow noopener">' in out2
    assert 'href="https://example.com/x">internal' in out2 and t.fix_rel(out2) == (out2, 0)

    out3, done, manual = t.replace_blocked(RAW, {"B084KRDD5F": None}, "www.amazon.com", "papalex-ex-20")
    assert (done, manual) == (1, 1)  # descriptive anchor repointed, generic "Shop on Amazon" left
    assert 'href="https://www.amazon.com/s?k=All-purpose+potting+mix&amp;tag=papalex-ex-20" rel="sponsored">All-purpose potting mix</a>' in out3
    out4, done, manual = t.replace_blocked(RAW, {"B084KRDD5F": "indoor potting mix"}, "www.amazon.com", "papalex-ex-20")
    assert (done, manual) == (2, 0)  # descriptive anchor keeps its own words, the generic button uses the fallback
    assert "s?k=All-purpose+potting+mix&amp;tag=papalex-ex-20" in out4 and "s?k=indoor+potting+mix&amp;tag=papalex-ex-20" in out4
    assert t.replace_blocked(out4, {"B084KRDD5F": "indoor potting mix"}, "www.amazon.com", "x")[1] == 0

    out5, n = t.add_disclosure(RAW, "Example & Co")
    assert n == 1 and out5.startswith('<p class="ace-disclosure"') and "Example &amp; Co earns" in out5 and "<!--" not in out5
    assert out5.endswith(RAW) and t.add_disclosure(out5, "Example") == (out5, 0)

    box = '<div class="ace-quick-picks">BOX</div>'
    out6, n = t.insert_box(RAW, box)
    assert n == 1 and out6.index("Intro paragraph.</p>") < out6.index("ace-quick-picks") < out6.index("<h2>Soil")
    assert t.insert_box(out6, box) == (out6, 0)
    assert t.insert_box("no paragraphs or headings", box)[1] == 0
    assert t.insert_box(RAW, "<div>unmarked</div>")[1] == 0  # refuses a box it could not find again
    blocks, _ = t.insert_box("<!-- wp:paragraph --><p>Hi</p><!-- /wp:paragraph --><h2>x</h2>", box)
    assert '<!-- /wp:paragraph -->\n\n<!-- wp:html -->\n<div class="ace-quick-picks">' in blocks  # stepped past the block


class FakeWP:
    """Stands in for WordPress: one post, records saves, serves the saved body as the live page."""
    store: dict = {}
    saves: list = []

    def __init__(self, domain, user_agent):
        pass

    def find(self, url, title=""):
        raw = FakeWP.store.get(url)
        return None if raw is None else {"kind": "posts", "id": 7, "link": url, "modified": "x", "raw": raw}

    def save(self, kind, post_id, content):
        FakeWP.saves.append((kind, post_id))
        url = next(iter(FakeWP.store))
        FakeWP.store[url] = content
        return content


def _fixer_setup(tmp_path):
    from ace import fixer
    url = "https://example.com/soil-guide/"
    body = "<html><head><title>Soil</title><meta name='description' content='d'></head><body><article>{}</article></body></html>"
    raw = RAW.replace("<p>Intro paragraph.</p>", "<p>Intro paragraph. " + "word " * 300 + "</p>")
    FakeWP.store, FakeWP.saves = {url: raw}, []
    cfg = Config("papalex", "www.amazon.com", [SITE], blocked_asins={"B084KRDD5F": "indoor potting mix"},
                 auto_fix=list(fixer.FIXES))
    page = parse(url, body.format(raw))
    page.status = 200
    rows = score.build_rows(cfg, {"example.com": [page]}, {}, {})

    def verify(live_url, site):
        live = parse(url, body.format(FakeWP.store[url]))
        live.status = 200
        return live

    return fixer, cfg, rows, url, raw, verify


def test_fixer_dry_run_changes_nothing(tmp_path):
    fixer, cfg, rows, url, raw, verify = _fixer_setup(tmp_path)
    actions = fixer.run(cfg, rows, tmp_path / "2026-11-26", backups=tmp_path / "b", pause=0, wp_factory=FakeWP, verify=verify, log=lambda *_: None)
    assert [a.status for a in actions] == ["would_change"] and set(actions[0].fixes) == {"tags", "rel", "disclosure", "blocked"}
    assert FakeWP.saves == [] and FakeWP.store[url] == raw
    assert "would_change" in (tmp_path / "2026-11-26" / "fix-log.csv").read_text()


def test_fixer_apply_saves_backs_up_and_verifies(tmp_path):
    fixer, cfg, rows, url, raw, verify = _fixer_setup(tmp_path)
    kwargs = dict(apply=True, backups=tmp_path / "b", pause=0, wp_factory=FakeWP, verify=verify, log=lambda *_: None)
    a = fixer.run(cfg, rows, tmp_path / "2026-11-26", **kwargs)[0]
    assert a.status == "fixed" and a.remaining == [] and FakeWP.saves == [("posts", 7)]
    assert (tmp_path / "b" / "example.com" / "7-2026-11-26.html").read_text() == raw
    saved = FakeWP.store[url]
    assert saved.startswith('<p class="ace-disclosure"') and "B000000002?tag=papalex-ex-20" in saved
    assert "someoneelse-20" in saved and "s?k=indoor+potting+mix" in saved and "s?k=All-purpose+potting+mix" in saved and "B084KRDD5F" not in saved
    # Second run on the same audit: nothing left to change, nothing saved.
    again = fixer.run(cfg, rows, tmp_path / "2026-11-26", **kwargs)[0]
    assert again.status == "nothing_to_change_in_post_body" and len(FakeWP.saves) == 1


def test_fixer_respects_config_and_access(tmp_path):
    fixer, cfg, rows, url, raw, verify = _fixer_setup(tmp_path)
    cfg.auto_fix = ["rel"]
    assert [a.fixes for a in fixer.plan(cfg, rows)] == [["rel"]]
    rows[0].site.skip_fix = "^/soil-"
    assert fixer.plan(cfg, rows) == []
    rows[0].site.skip_fix = ""

    class Locked(FakeWP):
        def find(self, url, title=""):
            from ace.wp import NoAccess
            raise NoAccess("401")

    a = fixer.run(cfg, rows, tmp_path / "r", apply=True, backups=tmp_path / "b", pause=0, wp_factory=Locked, verify=verify, log=lambda *_: None)[0]
    assert a.status == "no_access" and FakeWP.store[url] == raw


def test_wp_auth_env(monkeypatch):
    from ace import wp
    monkeypatch.setenv("WP_AUTH_PLANTASTICHAVEN_COM", "alex:abcd efgh")
    assert wp.auth_for("plantastichaven.com") == ("alex", "abcd efgh")
    assert wp.auth_for("example.com") is None


def test_affiliate_notice_wording_counts_as_disclosure():
    base = "<html><body><article>{}<p>" + "word " * 100 + '</p><a href="https://www.amazon.com/dp/B0CZPPGMWN?tag=papalex-ex-20" rel="sponsored">Mix</a></article><footer><a href="/affiliate-disclosure/">Affiliate disclosure</a></footer></body></html>'
    for notice in ("<p>When you buy through links on our site, we may earn a commission at no cost to you.</p>",
                   "<p>Transparency: Some product links on this page are affiliate links.</p>",
                   "<p>GearUpToFit may earn a commission from qualifying purchases through links on this page.</p>"):
        page = parse("https://example.com/a/", base.format(notice)); page.status = 200
        assert page.affiliate_notice and not page.disclosure
        assert "no_disclosure" not in score.page_issues(page, SITE, CFG)[0]
    bare = parse("https://example.com/a/", base.format("")); bare.status = 200  # footer link alone is not a statement
    assert not bare.affiliate_notice and "no_disclosure" in score.page_issues(bare, SITE, CFG)[0]


def test_box_placement_rules():
    from ace import transform as t
    box = '<div class="ace-quick-picks">BOX</div>'
    intro = "Intro sentence. " * 20
    # Skips a paragraph nested in a callout; uses the first top-level paragraph instead.
    html = f'<div class="answer"><p>Quick answer.</p></div><p>{intro}</p><h2>One</h2><p>Body</p>'
    out, n = t.insert_box(html, box)
    assert n == 1 and out.index("</div><p>Intro") < out.index("ace-quick-picks") < out.index("<h2>One")
    assert out.index(f"{intro}</p>") < out.index("ace-quick-picks")
    # No top-level paragraph before the H2, but there is an intro: goes just before the H2.
    html = f'<div class="answer"><p>{intro}</p></div><nav><ul><li>toc</li></ul></nav><h2>One</h2>'
    out, n = t.insert_box(html, box)
    assert n == 1 and out.index("</nav>") < out.index("ace-quick-picks") < out.index("<h2>One")
    # Post that opens with a heading and no intro: left alone.
    assert t.insert_box("<h2>One</h2><p>Body</p><h2>Two</h2>", box)[1] == 0
    # Hand-written placement.
    placed, n = t.insert_box("<h2>One</h2><table><tr><td>x</td></tr></table><p>after</p>", "<!-- place-after: </table> -->\n" + box)
    assert n == 1 and "</table>\n\n<div class=\"ace-quick-picks\">BOX</div>\n\n<p>after" in placed and "place-after" not in placed
    assert t.insert_box("<h2>One</h2><p>x</p>", "<!-- place-after: </table> -->\n" + box)[1] == 0
    # Block editor: wrapped at top level, raw inside an HTML block, refused inside other blocks.
    top = f"<!-- wp:paragraph --><p>{intro}</p><!-- /wp:paragraph --><!-- wp:heading --><h2>One</h2><!-- /wp:heading -->"
    out, n = t.insert_box(top, "<!-- place-after: <!-- /wp:paragraph --> -->\n" + box)
    assert n == 1 and "<!-- wp:html -->\n<div class=\"ace-quick-picks\">" in out
    inside_html = f"<!-- wp:html --><div class=\"a\"><p>Answer</p></div><h2>One</h2><!-- /wp:html -->"
    out, n = t.insert_box(inside_html, '<!-- place-after: <div class="a">.*?</div> -->\n' + box)
    assert n == 1 and out.count("<!-- wp:html -->") == 1 and '</div>\n\n<div class="ace-quick-picks">' in out
    assert t.insert_box(top, "<!-- place-after: Intro sentence -->\n" + box)[1] == 0  # would land inside a paragraph block


def test_curated_box_and_click_threshold(tmp_path, monkeypatch):
    from ace import fixer, fixes
    f, cfg, rows, url, raw, verify = _fixer_setup(tmp_path)
    cfg.auto_fix = ["box"]
    assert fixer.plan(cfg, rows) == []  # no Google clicks, no hand-written box
    folder = tmp_path / "boxes" / "example.com"; folder.mkdir(parents=True)
    (folder / "soil-guide.html").write_text('<!-- place-after: <h2>Soil</h2> -->\n<div class="ace-quick-picks">HAND</div>')
    monkeypatch.setattr(fixes, "CURATED", tmp_path / "boxes")
    monkeypatch.setattr(fixes.curated, "__defaults__", (tmp_path / "boxes",))
    action = fixer.plan(cfg, rows)[0]
    new, counts = fixer.transform_post(cfg, action, raw)
    assert counts["box_added"] == 1 and '<h2>Soil</h2>\n\n<div class="ace-quick-picks">HAND</div>' in new


def test_wp_find_falls_back_to_search():
    from ace.wp import WordPress

    class Resp:
        status_code = 200
        url = "x"
        def __init__(self, data): self._d = data
        def json(self): return self._d
        def raise_for_status(self): pass

    class Session:
        headers = {}
        calls = []
        def get(self, url, params=None, timeout=0):
            self.calls.append(url)
            item = {"id": 9, "link": "https://example.com/custom-url/", "modified": "m", "status": "publish", "content": {"raw": "RAW"}}
            if url.endswith("/search"):
                return Resp([{"id": 9, "url": "https://example.com/custom-url/", "subtype": "post"}])
            if url.endswith("/posts/9"):
                return Resp(item)
            return Resp([])  # slug lookups find nothing

    wp = WordPress("example.com", "ua", session=Session())
    assert wp.find("https://example.com/custom-url/") is None
    found = wp.find("https://example.com/custom-url/", "The Title")
    assert found == {"kind": "posts", "id": 9, "link": "https://example.com/custom-url/", "modified": "m", "raw": "RAW"}


def test_fix_log_keeps_earlier_fixed_rows(tmp_path):
    fixer, cfg, rows, url, raw, verify = _fixer_setup(tmp_path)
    kwargs = dict(apply=True, backups=tmp_path / "b", pause=0, wp_factory=FakeWP, verify=verify, log=lambda *_: None)
    fixer.run(cfg, rows, tmp_path / "r", **kwargs)
    fixer.run(cfg, rows, tmp_path / "r", **kwargs)  # second run finds nothing to change
    log = (tmp_path / "r" / "fix-log.csv").read_text()
    assert log.count(url) == 1 and ",fixed," in log and "nothing_to_change" not in log


def test_unattended_fixer_skips_sites_without_login(tmp_path, monkeypatch):
    fixer, cfg, rows, url, raw, verify = _fixer_setup(tmp_path)
    kwargs = dict(apply=True, backups=tmp_path / "b", pause=0, wp_factory=FakeWP, verify=verify, log=lambda *_: None, require_login=True)
    assert fixer.run(cfg, rows, tmp_path / "r", **kwargs) == [] and FakeWP.saves == []
    monkeypatch.setenv("WP_AUTH_EXAMPLE_COM", "user:pass word")
    assert [a.status for a in fixer.run(cfg, rows, tmp_path / "r", **kwargs)] == ["fixed"]


def test_loaded_share_detects_blocked_crawl():
    from ace import crawl
    from ace.page import Page
    ok, blocked = Page(url="a", status=200), Page(url="b", status=403)
    assert crawl.loaded_share({"x.com": [ok, ok], "y.com": [blocked]}) == 2 / 3
    assert crawl.loaded_share({"x.com": [blocked, blocked, ok]}) < 0.5 and crawl.loaded_share({}) == 1.0


def test_analytics_data_ranks_pages_google_ignores(tmp_path):
    folder = tmp_path / "example.com"; folder.mkdir()
    (folder / "amazon_clicks.csv").write_text("page,amazon_clicks\n/best-grow-lights/,4\n/other/#frag,9\n")
    (folder / "sessions.csv").write_text("page,sessions\nhttps://www.example.com/best-grow-lights,120\n")
    ga = data.load_ga4("example.com", tmp_path)
    assert ga == {"example.com/best-grow-lights": {"url": "https://example.com/best-grow-lights/", "amazon_clicks": 4.0, "sessions": 120.0}}
    page = parse("https://example.com/best-grow-lights/", HTML); page.status = 200
    row = score.build_rows(CFG, {"example.com": [page]}, {}, {}, {"example.com": ga})[0]
    assert row.visits == 120 and row.reachable_clicks == 120 and row.score == round(120 * 0.7, 2)
    assert "earning_page_noindexed" not in row.issues
    page.noindex = True
    row = score.build_rows(CFG, {"example.com": [page]}, {}, {}, {"example.com": ga})[0]
    assert "earning_page_noindexed" in row.issues


def test_crawl_adds_analytics_pages_missing_from_sitemaps(monkeypatch):
    from ace import crawl
    monkeypatch.setattr(crawl, "discover", lambda site: {"https://example.com/a/": ["https://example.com/sitemap.xml"]})
    monkeypatch.setattr(crawl, "audit_url", lambda url, site: crawl.Page(url=url, status=200))
    pages, sm = crawl.crawl(Site(domain="example.com", name="E"), log=lambda *_: None, extra_urls=["https://example.com/a", "https://example.com/hidden/"])
    assert [p.url for p in pages] == ["https://example.com/a/", "https://example.com/hidden/"]
    assert sm["https://example.com/hidden/"] == [crawl.ANALYTICS_ONLY]


def test_indexnow_submits_only_new_or_changed_indexable_pages(tmp_path):
    from ace import indexnow

    class Resp:
        def __init__(self, code, text=""): self.status_code, self.text = code, text

    key = "a" * 32
    posted = []
    get = lambda url, **kw: Resp(200, key if url == f"https://example.com/{key}.txt" else "other")
    post = lambda url, json, **kw: (posted.append(json), Resp(202))[1]
    a = _page("https://example.com/a/", "alpha " * 400, "A")
    b = _page("https://example.com/b/", "beta " * 400, "B")
    hidden = _page("https://example.com/hidden/", "gamma " * 400, "H"); hidden.noindex = True
    rows = score.build_rows(CFG, {"example.com": [a, b, hidden]}, {}, {})
    kw = dict(root=tmp_path / "state", key=key, get=get, post=post, log=lambda *_: None)

    dry = indexnow.run(rows, tmp_path / "2026-11-26", **kw)[0]
    assert dry.status == "would_submit" and posted == [] and sorted(dry.urls) == ["https://example.com/a/", "https://example.com/b/"]

    first = indexnow.run(rows, tmp_path / "2026-11-26", apply=True, **kw)[0]
    assert first.status == "submitted" and posted[0]["host"] == "example.com" and posted[0]["keyLocation"] == f"https://example.com/{key}.txt"
    assert sorted(posted[0]["urlList"]) == ["https://example.com/a/", "https://example.com/b/"]  # noindexed page never sent

    again = indexnow.run(rows, tmp_path / "2026-11-27", apply=True, **kw)[0]
    assert again.status == "nothing_new" and again.unchanged == 2 and len(posted) == 1

    b2 = _page("https://example.com/b/", "beta " * 200 + "delta " * 200, "B")
    rows2 = score.build_rows(CFG, {"example.com": [a, b2, hidden]}, {}, {})
    changed = indexnow.run(rows2, tmp_path / "2026-11-28", apply=True, **kw)[0]
    assert changed.urls == ["https://example.com/b/"] and posted[-1]["urlList"] == ["https://example.com/b/"]
    assert key not in (tmp_path / "state" / "example.com.json").read_text()  # the key is never stored


def test_indexnow_refuses_when_key_file_is_wrong(tmp_path):
    from ace import indexnow

    class Resp:
        status_code, text = 200, "some-other-key"

    posted = []
    rows = score.build_rows(CFG, {"example.com": [_page("https://example.com/a/", "alpha " * 400, "A")]}, {}, {})
    kw = dict(root=tmp_path / "state", get=lambda *a, **k: Resp(), post=lambda *a, **k: posted.append(1), log=lambda *_: None)
    assert indexnow.run(rows, tmp_path / "r", apply=True, key="b" * 32, **kw)[0].status == "key_file_invalid"
    assert indexnow.run(rows, tmp_path / "r", apply=True, key="", **kw)[0].status == "no_key" and posted == []


def test_markdown_renderer_covers_report_syntax():
    from ace import site
    out = site.markdown("# Title\n\nA **bold** `code` line with https://example.com/a/ in it.\n\n- one\n- two\n  continued\n\n| Page | Clicks |\n|---|---|\n| https://example.com/x/ | 3 |\n| b | 4 |\n\n1. first\n2. second <b>\n", max_rows=1)
    assert '<h1 id="title">Title</h1>' in out and "<strong>bold</strong>" in out and "<code>code</code>" in out
    assert '<a href="https://example.com/a/" target="_blank" rel="noopener">https://example.com/a/</a>' in out
    assert "<ul><li>one</li><li>two continued</li></ul>" in out and "<ol><li>first</li><li>second &lt;b&gt;</li></ol>" in out
    assert "<th>Page</th>" in out and out.count("<tr>") == 2 and "Showing 1 of 2 rows." in out


def test_site_build(tmp_path, monkeypatch):
    import json
    from ace import site
    monkeypatch.setattr(site, "repository_public", lambda slug: None)  # no network in tests
    old, rep = tmp_path / "reports" / "2026-11-25", tmp_path / "reports" / "2026-11-26"
    old.mkdir(parents=True); rep.mkdir()
    head = "site,url,status,amazon_links,first_link_depth,tags,ga_amazon_clicks,gsc_impressions,score,issues\n"
    (old / "pages.csv").write_text(head + "example.com,https://example.com/a/,200,1,0.1,me-20,,,0,\n")
    (rep / "pages.csv").write_text(
        head + "example.com,https://example.com/a/,200,3,0.1,me-20,2,40,1.5,untagged_link\n"
        "example.com,https://example.com/b/,200,1,0.8,other-20,,,0,first_link_very_late other_site_tag\n"
        "example.com,https://example.com/c/,200,0,,,,,0,no_amazon_links\n")
    (rep / "links.csv").write_text("site,page,href,kind,tag,asin,rel_ok,in_site_chrome,name\n"
                                   "example.com,https://example.com/a/,https://www.amazon.com/dp/B000000001?tag=me-20,product,me-20,B000000001,1,0,Widget\n"
                                   "example.com,https://example.com/a/,https://www.amazon.com/dp/B000000002?tag=me-20,product,me-20,B000000002,1,1,Footer\n")
    fixes_dir = rep / "fixes" / "example.com"; fixes_dir.mkdir(parents=True); (fixes_dir / "b.html").write_text("<div></div>")
    (rep / "summary.md").write_text("# Audit\n\n| Site | Pages |\n|---|---|\n| Example | 3 |\n")
    (rep / "fix-log.csv").write_text("site,url,post_id,fixes,status,changes,still_failing_on_live_page\nexample.com,https://example.com/a/,7,box,fixed,box_added=1,\n"
                                     "example.com,https://example.com/b/,8,box,skipped,,\n")
    (rep / "indexnow-log.csv").write_text("site,host,status,urls_new_or_changed,urls_unchanged,detail\nexample.com,example.com,submitted,2,0,HTTP 200 accepted\n")
    docs = tmp_path / "docs"; docs.mkdir(); (docs / "experiments.md").write_text("# Experiments\n\nText.\n")
    state = tmp_path / "state"; state.mkdir(); (state / "example.com.json").write_text('{"submitted": {"a": "1", "b": "2"}, "last_submission": "2026-11-26"}')
    ga = tmp_path / "ga4" / "example.com"; ga.mkdir(parents=True); (ga / "amazon_clicks.csv").write_text("page,amazon_clicks\n/a/,2\n")
    cfg = Config(account_tag_prefix="me", marketplace="www.amazon.com", repository="owner/repo", auto_fix=["box"],
                 sites=[Site(domain="example.com", name="Example", tags=["me-20"], gsc_property="sc-domain:example.com")])
    out = site.build(tmp_path / "dist", cfg=cfg, reports=tmp_path / "reports", docs=docs, state=state, gsc=tmp_path / "gsc",
                     ga4=tmp_path / "ga4", mirrors=[tmp_path / "public"])
    for name in ("index.html", "app.css", "app.js", "data.json", "links.json", "_headers", "robots.txt", "downloads/pages.csv"):
        assert (out / name).exists() and (tmp_path / "public" / name).exists(), name
    assert 'name="robots" content="noindex, nofollow"' in (out / "index.html").read_text()
    data = json.loads((out / "data.json").read_text())
    assert data["generated"] == "2026-11-26" and data["previous"] == "2026-11-25" and data["repository"] == "owner/repo"
    s = data["sites"][0]
    assert (s["pages"], s["with_links"], s["links"], s["early"], s["late"], s["ga_clicks"], s["submitted"]) == (3, 2, 4, 1, 1, 2, 2)
    assert s["has_ga"] and not s["has_gsc"] and s["prev"]["links"] == 1 and s["tags_seen"] == {"me-20": 1, "other-20": 1}
    page = dict(zip(data["cols"], data["pages"][0]))
    assert page["url"] == "https://example.com/a/" and page["site"] == 0 and page["aclicks"] == 2 and page["score"] == 1.5
    assert data["issues"]["untagged_link"]["severity"] == "critical" and data["issues"]["untagged_link"]["action"]
    assert data["attention"][0]["issue"] == "untagged_link" and any("Search Console" in a["title"] for a in data["attention"])
    assert [f["url"] for f in data["fixes"]] == ["https://example.com/a/"]  # skipped rows are not activity
    assert json.loads((out / "links.json").read_text()) == {  # links in menus and footers are left out
        "https://example.com/a/": [["https://www.amazon.com/dp/B000000001?tag=me-20", "product", "me-20", "B000000001", "Widget"]]}
    assert [h["date"] for h in data["history"]] == ["2026-11-25", "2026-11-26"] and data["history"][-1]["to_fix"] == 2
    assert s["history"][0]["links"] == 1 and s["new_pages"] == 2 and s["gone_pages"] == 0 and s["to_fix"] == 2 and s["prev"]["issues"] == {}
    assert data["drafts"] == {"https://example.com/b/": (fixes_dir / "b.html").as_posix()}
    late, untagged = data["issues"]["first_link_very_late"], data["issues"]["untagged_link"]
    assert (late["fix"], late["fix_on"], untagged["fix"], untagged["fix_on"]) == ("box", True, "tags", False)
    assert not data["issues"]["no_amazon_links"]["to_fix"] and data["issues"]["no_amazon_links"]["fix"] == ""
    assert data["submissions"][0]["total"] == 2 and {n["slug"] for n in data["notes"]} == {"full-report", "experiments"}


def test_dashboard_script_uses_only_fields_the_build_writes():
    """The page reads data.json by field name. A renamed field would fail silently in the browser."""
    import re
    from ace import site
    js = (site.ASSETS / "app.js").read_text()
    used = set(re.findall(r"\bp\.(\w+)\b", js))
    derived = {"s", "codes", "path", "sev", "fix", "visits", "url", "status", "search", "indexed"}
    assert used - derived <= set(site.COLS), used - derived - set(site.COLS)


def test_ensure_folders(tmp_path):
    from ace import data
    data.ensure_folders(["example.com"], root=tmp_path)
    (tmp_path / "gsc" / "example.com" / "pages.csv").write_text("x")
    data.ensure_folders(["example.com"], root=tmp_path)
    assert (tmp_path / "ga4" / "example.com" / ".gitkeep").exists() and (tmp_path / "associates" / ".gitkeep").exists()
    assert data.load_ga4("example.com", root=tmp_path / "ga4") == {}


def test_short_name_keeps_product_names_and_rejects_calls_to_action():
    assert fixes.short_name("XLUX Soil Moisture Meter, Plant Water Monitor, Hygrometer") == "XLUX Soil Moisture Meter"
    assert fixes.short_name("Deep Work by Cal Newport Amazon product image") == "Deep Work by Cal Newport"
    assert fixes.short_name("Time Timer MOD Home Edition 60 Minute Visual Timer Amazon product") == "Time Timer MOD Home Edition 60 Minute Visual Timer"
    assert fixes.short_name("Snow Crash cover") == "Snow Crash"
    assert fixes.short_name("VIVOSUN 6.5 Inch Gardening Scissors Hand Pruner Pruning Shear with Titanium") == "VIVOSUN 6.5 Inch Gardening Scissors Hand Pruner Pruning"
    assert fixes.short_name("4 Pack Moss Pole - Stackable up to 48 inches") == "4 Pack Moss Pole"
    assert fixes.short_name("Nike Men's Pegasus Turbo Next Nature Running Shoes (Mineral Teal/Barely Volt)") == "Nike Men's Pegasus Turbo Next Nature Running Shoes"
    assert fixes.short_name("The Lean Startup: How Today's Entrepreneurs Use Continuous Innovation to Create") == "The Lean Startup"
    assert fixes.short_name("Nature Made Vitamin D3 1,000 IU (25 mcg), 100 Softgels") == "Nature Made Vitamin D3 1,000 IU (25 mcg)"
    for junk in ("Sweeten Naturally Today!", "Shop Black/Faded Black →", "Discover the fēnix 8", "Check price on Amazon", "View on Amazon", "Buy now", "B0", ""):
        assert fixes.short_name(junk) == "", junk


def test_box_stays_out_of_hero_header_and_can_be_moved():
    from ace import transform as t
    box = '<div class="ace-quick-picks"><p>Quick picks</p><ul><li>x</li></ul></div>'
    intro = " ".join(["word"] * 40)
    post = f'<article class="x"><header class="hero"><h1>T</h1><p>Hero line.</p></header><p>{intro}</p><h2>One</h2><p>Body</p></article>'
    out, n = t.insert_box(post, box)
    assert n == 1 and out.index("ace-quick-picks") > out.index("</header>") and out.index("ace-quick-picks") < out.index("<h2>")
    nested = f'<article><header><p>{intro}</p></header><section><h2>One</h2><p>Body</p></section></article>'
    out, n = t.insert_box(nested, box)  # the first H2 sits as deep as the hero paragraph: still not the header
    assert n == 1 and out.index("</header>") < out.index("ace-quick-picks") < out.index("<h2>")
    styled = f'<style>.a{{color:red}}</p>\n<p>.b{{margin:0}}</style><p>{intro}</p><h2>One</h2><p>Body</p>'
    out, n = t.insert_box(styled, box)  # a stray </p> inside a stylesheet is not a place for a box
    assert n == 1 and out.index("</style>") < out.index("ace-quick-picks") < out.index("<h2>")
    assert t.insert_box(f'<style>p{{}}</p><h2>One</h2><p>{intro}</p></style>', box)[1] == 0
    misplaced = post.replace("<p>Hero line.</p>", "<p>Hero line.</p>\n\n<!-- wp:html -->\n" + box + "\n<!-- /wp:html -->\n\n")
    cleaned, taken = t.remove_box(misplaced)
    assert taken == box and "ace-quick-picks" not in cleaned and "wp:html" not in cleaned
    assert t.remove_box(post) == (post, "")


def test_box_names_products_from_card_headings_and_adds_searches():
    card = lambda asin, title, cta="Check Price on Amazon": (
        f'<div class="card"><a href="https://www.amazon.com/dp/{asin}/?tag=me-20"><img src="x.jpg"></a>'
        f'<h3>{title}</h3><p>Good for long runs.</p><a href="https://www.amazon.com/dp/{asin}/?tag=me-20">{cta}</a></div>')
    filler = "<p>" + " ".join(["word"] * 300) + "</p>"
    html_ = ("<html><body><h1>Guide</h1>" + filler + "<h2>Recommended gear</h2>"
             + card("B000000001", "Garmin Fenix 8 AMOLED 47mm") + card("B000000002", "2. Coros Pace 3 GPS Watch")
             + "<h3>Why trust us</h3><p>x</p>" + '<a href="https://www.amazon.com/dp/B000000003/?tag=me-20">View on Amazon</a>'
             + '<p><a href="https://www.amazon.com/s?k=running+belt+with+bottle&tag=me-20">compare running belts on Amazon</a></p></body></html>')
    page = parse("https://example.com/guide/", html_)
    cta = [l for l in page.links if l.text.startswith("Check")]
    assert [l.heading for l in cta] == ["Garmin Fenix 8 AMOLED 47mm", "2. Coros Pace 3 GPS Watch"]
    assert all(l.heading == "" for l in page.links if not l.text.strip())  # image links take no heading
    row = score.Row(site=Site(domain="example.com", name="Example"), page=page, gsc=None)
    out = fixes.box(row)
    assert ">Garmin Fenix 8 AMOLED 47mm</a>" in out and ">Coros Pace 3 GPS Watch</a>" in out and "Why trust us" not in out
    assert ">Running belt with bottle</a> <span" in out and "(Amazon search)" in out and "B000000003" not in out
    assert "Quick picks from this guide" in out
    assert fixes.heading_name("Final Verdict") == "" and fixes.heading_name("How to choose a watch") == ""
    assert fixes.heading_name("Fitbit Air Alternative Listing") == "" and fixes.short_name("McDavid Waist Trimmer Belt — Best low-profile gym belt") == "McDavid Waist Trimmer Belt"
    prose = parse("https://example.com/p/", "<html><body>" + filler + '<h3>Smart Home Integration</h3><p>Pair it with an <a href="https://www.amazon.com/dp/B000000009/?tag=me-20">Amazon Alexa routine</a>.</p></body></html>')
    assert fixes.box(score.Row(site=Site(domain="example.com", name="Example"), page=prose, gsc=None)) is None  # a text link is not a card button
    only_search = parse("https://example.com/s/", "<html><body>" + filler + '<p><a href="https://www.amazon.com/s?k=outlet+timer+for+grow+lights&tag=me-20">compare timers on Amazon</a></p></body></html>')
    assert "Quick links from this guide" in fixes.box(score.Row(site=Site(domain="example.com", name="Example"), page=only_search, gsc=None))
    policy = parse("https://example.com/cookie-policy/", "<html><body>" + filler + '<p><a href="https://www.amazon.com/gp/help/customer/display.html?nodeId=1">Amazon privacy</a></p></body></html>')
    assert policy.content_links == [] and policy.first_link_depth is None


def test_scoring_combines_google_and_bing_and_reads_index_status():
    from ace.data import GscRow
    site = Site(domain="example.com", name="Example")
    cfg = Config(account_tag_prefix="me", marketplace="www.amazon.com", sites=[site])
    body = "<p>" + " ".join(["word"] * 400) + "</p>"
    pages = {"example.com": [
        parse("https://example.com/a/", f"<html><head><title>A</title></head><body>{body}</body></html>"),
        parse("https://example.com/b/", f"<html><head><title>B</title></head><body>{body}</body></html>"),
        parse("https://example.com/c/", f"<html><head><title>C</title><link rel='canonical' href='https://example.com/c/'></head><body>{body}</body></html>"),
    ]}
    for p in pages["example.com"]:
        p.status = 200
    rows = {r.page.url: r for r in score.build_rows(
        cfg, pages, {"example.com": {"example.com/a": GscRow(2, 200, 3)}}, {}, {},
        bing_by_site={"example.com": {"example.com/a": GscRow(5, 1000, 2), "example.com/b": GscRow(0, 40, 9)}},
        index_by_site={"example.com": {
            "example.com/a": {"verdict": "NEUTRAL", "coverage": "Crawled - currently not indexed"},
            "example.com/b": {"verdict": "NEUTRAL", "coverage": "URL is unknown to Google"},
            "example.com/c": {"verdict": "PASS", "coverage": "Submitted and indexed", "google_canonical": "https://example.com/other/"}}},
        bing_errors_by_site={"example.com": {"example.com/b": {"issues": "4xx"}}})}
    a, b, c = rows["https://example.com/a/"], rows["https://example.com/b/"], rows["https://example.com/c/"]
    assert a.search_clicks == 7 and a.visits == 7
    assert a.reachable_clicks == max(2, 200 * score.expected_ctr(3)) + max(5, 1000 * score.expected_ctr(2))
    assert "low_bing_ctr" in a.issues and "low_serp_ctr" in a.issues
    assert "demand_page_not_in_google" in a.issues and "not_in_google" not in a.issues
    assert "demand_page_not_in_google" in b.issues and "bing_crawl_error" in b.issues  # Bing impressions count as demand
    assert c.issues.count("google_canonical_mismatch") == 1 and "not_in_google" not in c.issues
    quiet = score.build_rows(cfg, {"example.com": [pages["example.com"][2]]}, {}, {}, {},
                             index_by_site={"example.com": {"example.com/c": {"verdict": "NEUTRAL", "coverage": "Discovered - currently not indexed"}}})
    assert "not_in_google" in quiet[0].issues
    stale = score.build_rows(cfg, {"example.com": [pages["example.com"][2]]}, {}, {}, {},
                             index_by_site={"example.com": {"example.com/c": {"verdict": "NEUTRAL", "coverage": "Excluded by \u2018noindex\u2019 tag"}}})
    assert stale[0].issues.count("google_verdict_outdated") == 1 and "not_in_google" not in stale[0].issues



def test_loaders_merge_url_variants_and_dashboard_merges_query_fragments(tmp_path):
    from ace import site
    gsc_dir = tmp_path / "gsc" / "example.com"; gsc_dir.mkdir(parents=True)
    (gsc_dir / "pages.csv").write_text("page,clicks,impressions,position\n"
                                       "https://example.com/a,0,191,50\nhttps://example.com/a/,2,9,10\nhttps://www.example.com/a/?utm_source=x,1,0,0\n")
    rows, _ = data.load_gsc("example.com", tmp_path / "gsc")
    a = rows["example.com/a"]
    assert (a.clicks, a.impressions) == (3, 200) and a.position == round((50 * 191 + 10 * 9) / 200, 2)
    (gsc_dir / "queries.csv").write_text("page,query,clicks,impressions,position\n"
                                         "https://example.com/a/#s1,pots,1,8,8\nhttps://example.com/a/#s2,pots,0,2,3\nhttps://example.com/a/,other,0,1,1\n")
    q = site.queries_by_page(["example.com"], ["https://example.com/a/"], tmp_path / "gsc", tmp_path / "bing")
    assert q["https://example.com/a/"]["g"] == [["pots", 1, 10, 7.0], ["other", 0, 1, 1.0]]


def test_inspect_survives_network_errors_and_keeps_going():
    import requests
    calls = []

    class Session:
        def get(self, url, timeout):
            return _Resp({"siteEntry": [{"siteUrl": "sc-domain:a.com", "permissionLevel": "siteFullUser"},
                                        {"siteUrl": "sc-domain:b.com", "permissionLevel": "siteFullUser"}]})
        def post(self, url, json, timeout):
            calls.append(json["inspectionUrl"])
            if json["inspectionUrl"].endswith("/flaky/"):
                raise requests.ReadTimeout("timed out")
            return _Resp({"inspectionResult": {"indexStatusResult": {"verdict": "PASS", "coverageState": "Submitted and indexed"}}})

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        sites = [(Site(domain="a.com", name="A"), ["https://a.com/flaky/", "https://a.com/ok/"]), (Site(domain="b.com", name="B"), ["https://b.com/x/"])]
        done = gsc.inspect(sites, root=tmp, session_factory=Session, today=date(2026, 11, 27), log=lambda *_: None)
        assert done == {"a.com": 1, "b.com": 1}  # the flaky URL was retried, then skipped; the next site still ran
        assert calls.count("https://a.com/flaky/") == 3



def test_ga4_tag_checks_do_not_raise_false_alarms(tmp_path):
    from ace import ga4

    class Blocked:
        status_code, text = 403, "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x.js'></script></html>"
    assert ga4.live_tags("example.com", get=lambda *a, **k: Blocked())["checked"] is False  # a challenge page proves nothing
    class SiteKit:
        status_code, text = 200, "<script src='https://www.googletagmanager.com/gtag/js?id=GT-ABC1234'></script>"
    tags = ga4.live_tags("example.com", get=lambda *a, **k: SiteKit())
    assert tags["checked"] and tags["other"] and not tags["ga"]

    class NoAdmin:  # the Admin API refuses: no tag may be called "unreadable"
        def get(self, url, params=None, timeout=None):
            return _Resp({"error": "API not enabled"}, status=403)
        def post(self, url, json, timeout):
            return _Resp({"rows": [], "rowCount": 0})
    page = lambda url, **kw: type("P", (), {"status_code": 200, "text": "gtag('config','G-ABCDEF12')"})()
    meta = ga4.pull([Site(domain="example.com", name="E", ga4_properties=["5"])], root=tmp_path, session=NoAdmin(),
                    today=date(2026, 11, 27), log=lambda *_: None, get=page)["example.com"]
    assert meta["unreadable_tags"] == [] and any("could not check" in n for n in meta["notes"])



def test_setup_access_creates_once_then_reuses():
    import importlib.util
    spec = importlib.util.spec_from_file_location("setup_access", Path(__file__).parent.parent / "infra" / "setup_access.py")
    sa = importlib.util.module_from_spec(spec); spec.loader.exec_module(sa)
    state = {"org": None, "idps": [], "apps": [], "policies": {}, "vars": None, "calls": []}

    class Resp:
        def __init__(self, result, ok=True):
            self.status_code = 200 if ok else 403
            self.body = {"success": ok, "result": result, "errors": [] if ok else [{"code": 10000, "message": "Authentication error"}]}
        def json(self):
            return self.body

    class Session:
        def request(self, method, url, headers=None, timeout=None, json=None, params=None):
            path = url.split("/accounts/acc")[1]
            state["calls"].append((method, path))
            if path == "/access/organizations":
                if method == "POST":
                    state["org"] = {"auth_domain": json["auth_domain"]}
                return Resp(state["org"], ok=state["org"] is not None or method == "POST")
            if path == "/access/identity_providers":
                if method == "POST":
                    state["idps"].append({"id": "otp1", **json})
                return Resp(state["idps"] if method == "GET" else state["idps"][-1])
            if path == "/access/apps":
                if method == "POST":
                    state["apps"].append({"id": "app1", "aud": "AUD1", **json})
                return Resp(state["apps"] if method == "GET" else state["apps"][-1])
            if path.startswith("/access/apps/app1/policies"):
                pol = state["policies"]
                if method == "GET":
                    return Resp(list(pol.values()))
                pol["p1"] = {"id": "p1", **json}
                return Resp(pol["p1"])
            if path == "/pages/projects/proj" and method == "GET":
                return Resp({"name": "proj"})
            if path == "/access/apps/app1":
                state["apps"][0].update(json)
                return Resp(state["apps"][0])
            if path == "/pages/projects/proj":
                state["vars"] = json["deployment_configs"]
                return Resp({})
            if path == "/pages/projects/proj/deployments":
                return Resp([{"id": "d1"}])
            if path.endswith("/retry"):
                return Resp({"id": "d2"})
            if path == "/pages/projects/proj/deployments/d2":
                return Resp({"latest_stage": {"name": "deploy", "status": "success"}, "url": "https://d2.proj.pages.dev"})
            raise AssertionError(path)

    access = sa.Client("t", "acc", session=Session())
    quiet = lambda *_: None
    import pytest
    with pytest.raises(sa.CloudflareError):  # no team yet and none given
        sa.ensure_organization(access, None, log=quiet)
    team = sa.ensure_organization(access, "myteam", log=quiet)
    otp = sa.ensure_otp(access, log=quiet)
    app = sa.ensure_app(access, "proj.pages.dev", otp, log=quiet)
    sa.ensure_policy(access, app["id"], ["owner@example.com"], log=quiet)
    assert team == "myteam.cloudflareaccess.com" and otp == "otp1"
    assert [d["uri"] for d in app["destinations"]] == ["proj.pages.dev", "*.proj.pages.dev"] and app["session_duration"] == "720h"
    assert app["allowed_idps"] == ["otp1"] and app["auto_redirect_to_identity"] is True
    assert state["policies"]["p1"]["include"] == [{"email": {"email": "owner@example.com"}}]
    redirect = lambda url, **kw: type("R", (), {"status_code": 302, "headers": {"Location": f"https://{team}/cdn-cgi/access/login/proj.pages.dev?x=1"}})()
    assert sa.access_enforced("proj.pages.dev", team, get=redirect, wait=0, log=quiet)
    not_yet = lambda url, **kw: type("R", (), {"status_code": 401, "headers": {}})()
    assert not sa.access_enforced("proj.pages.dev", team, get=not_yet, wait=0, log=quiet)
    assert sa.switch_dashboard(sa.Client("t", "acc", session=Session()), "proj", team, app["aud"], log=quiet).startswith("success")
    assert state["vars"]["production"]["env_vars"]["ACCESS_AUD"]["value"] == "AUD1" and state["vars"]["production"]["fail_open"] is False
    assert sa.rollback(sa.Client("t", "acc", session=Session()), "proj", log=quiet).startswith("success")
    assert state["vars"]["production"]["env_vars"] == {"ACCESS_TEAM_DOMAIN": None, "ACCESS_AUD": None}
    assert not sa.covers({"domain": "proj.pages.dev"}, "proj.pages.dev")  # an app without the wildcard must stop the switch
    before = len(state["idps"]), len(state["apps"]), len(state["policies"])
    sa.ensure_otp(access, log=quiet); sa.ensure_app(access, "proj.pages.dev", otp, log=quiet); sa.ensure_policy(access, "app1", ["owner@example.com"], log=quiet)
    assert (len(state["idps"]), len(state["apps"]), len(state["policies"])) == before  # a second run creates nothing new


@pytest.mark.parametrize("script", ["tests/middleware.test.mjs", "infra/gateway/worker.test.mjs"])
def test_sign_in_checks(script):
    """The dashboard's own sign-in (functions/_middleware.js) and the email-code gateway
    (infra/gateway/worker.js): signed-in requests pass, every missing or forged sign-in is refused."""
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([node, str(root / script)], capture_output=True, text=True, timeout=180,
                            env={**os.environ, "NODE_NO_WARNINGS": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
