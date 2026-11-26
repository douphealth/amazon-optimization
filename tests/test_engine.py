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
