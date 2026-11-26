import json
from datetime import date
from pathlib import Path

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


def test_gsc_pull_writes_csv(tmp_path):
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"rows": [{"keys": ["https://example.com/a/"], "clicks": 3, "impressions": 90, "position": 6.5}]}

    class Session:
        calls = []
        def post(self, url, json, timeout):
            self.calls.append((url, json))
            return Resp()

    session = Session()
    site = Site(domain="example.com", name="Example", gsc_property="sc-domain:example.com")
    gsc.pull([site], days=28, root=tmp_path, session=session, today=date(2026, 11, 25), log=lambda *_: None)
    url, body = session.calls[0]
    assert "sc-domain%3Aexample.com" in url
    assert body["startDate"] == "2026-10-26" and body["endDate"] == "2026-11-22"
    rows, meta = data.load_gsc("example.com", tmp_path)
    assert rows["example.com/a"].clicks == 3 and meta["end"] == "2026-11-22"


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
