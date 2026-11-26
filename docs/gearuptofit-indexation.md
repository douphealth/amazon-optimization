# GearUpToFit: no Google traffic, but still the main source of Amazon clicks

Status on 2026-11-26. GearUpToFit holds 2,012 of the portfolio's Amazon links.

## The picture changed once Google Analytics was connected (2026-11-26)

| Fact (Nov 12-25, 14 days) | Source |
|---|---|
| 638 organic-search visits, 430 of them engaged. Search Console shows 0 Google clicks in the same period, so these come from other search engines. Which ones is not yet known | Google Analytics vs Search Console |
| 63 of the 66 Amazon clicks Analytics recorded across the portfolio came from GearUpToFit | Google Analytics outbound-click events |
| The clicks come from buying guides: kids' smartwatches (9), dumbbells (6), supination shoes, muscle supplements and treadmills (4 each), plus the shoe-finder app (14 across its pages) | Same; full list in `reports/2026-11-26/summary.md` |
| 6,033 "direct" visits with a 6% engagement rate. That pattern is typical of bots, not readers | Google Analytics |
| Google's Page indexing report: 1 page indexed, 701 not. 366 "Crawled - currently not indexed", 279 "Discovered - currently not indexed", 46 noindex, 5 not found, 5 redirect, 0 server errors | Screenshot from the site owner, report dated 2026-11-16 |

**What this means.** Google has crawled the site and chosen not to index it; nothing is blocking its
crawler. That is an automated quality judgement and will not be fixed quickly. But the site still
earns: other search engines send it about 45 visits a day, and those visitors click through to Amazon.
The priority is to protect and grow that traffic, not to make risky changes in the hope of moving Google.

**Decisions**

- `watch-match` is not being noindexed. A noindex tag applies to every search engine, so it would
  also remove those pages from the engines that do send visitors.
- Any future prune must check Analytics for visits and Amazon clicks first, not only Search Console.

## Pages wrongly kept out of search engines

**76 published posts carry `noindex` although they are not in the September prune list.** They
include current buying guides and product reviews (Brooks Ghost 17, Saucony Ride 19, Apple Watch
Series 10, Pixel Watch 3, best treadmills for home, best running shoes for beginners and for flat
feet). 42 of them carry Amazon links, 302 links in total. The full list is in
`docs/gearuptofit-noindexed-outside-prune.csv`.

Three of them, plus one shoe-finder page, produced Amazon clicks in the last 14 days:

| Page | Amazon clicks |
|---|---|
| /review/best-treadmills-for-home/ | 4 |
| /review/best-compression-boots/ (this one is in the prune list) | 3 |
| /review/best-running-shoes-for-heavy-runners/ | 1 |
| /shoe-finder/shoes/topo-ultrafly-6/ | 4 |

### Which layer decides (corrected 2026-11-26)

An earlier version of this note blamed a Cloudflare Worker. That was wrong. All 85 Workers on the
account were downloaded and read: none sets noindex on post pages, and the sitemap Worker simply
mirrors WordPress's own post sitemaps.

**The rule lives in the child theme, `wp-content/themes/twentyten-child/functions.php`**, in the
block that starts "Prune: noindex,follow for zero-value posts (added 2026-09-24)". It holds 848 post
IDs in `gutf_prune_noindex_ids()` and applies them to Yoast's robots array, to core `wp_robots`, and
to the sitemap exclusion filter. Its own change log reads:

- 2026-09-24: 783 posts with 0 clicks and under 50 impressions on Bing and Google over 16 months.
- 2026-10-04 to 2026-11-15: individual posts released by `release_pages.py`.
- 2026-11-19: "added 90 IDs with zero Bing impressions, prune phase 2", by `prune_add.py`.

All 76 posts in `docs/gearuptofit-noindexed-outside-prune.csv` are in that list, including the
three earning review pages. The list is maintained by scripts in a local project folder
(`backups/2026-10-12/owner/release_pages.py`), so it should be changed with those scripts, not by
hand-editing the theme file, or the two will drift apart.

**Fixed on 2026-11-26.** Post IDs 92024 (best treadmills for home), 91836 (best running shoes for
heavy runners) and 90633 (best compression boots) were removed from the list in the theme editor,
with a dated line added to the block's change log. The list now holds 845 IDs. The previous file is
saved as a backup. Add the three IDs to the release records in the project folder so the prune
scripts do not put them back.

Result, checked on the live site: all three pages serve `index, follow` with a canonical tag to
desktop and mobile, `sitemap-posts.xml` lists them (501 URLs), and they were submitted through
IndexNow. Pages still on the list (for example Brooks Ghost 17) are unchanged.

Making a robots change visible takes three cache steps, in this order:

1. Delete the pages from the Seraphinite Accelerator cache (Manage > Operate > Specified URLs > Delete cache).
2. Purge the same URLs from Cloudflare.
3. Purge `sitemap-posts.xml` and the two origin post sitemaps from Cloudflare.

Before any further prune phase, check Google Analytics as well as Bing and Search Console: a page can
show zero search impressions and still be one visitors reach and buy from. One shoe-finder page
(`/shoe-finder/shoes/topo-ultrafly-6/`) still earns Amazon clicks while noindexed; it belongs to the
shoe-finder app, not WordPress.

Left over and safe to remove: the two code snippets named "PGCC gearuptofit prune noindex
2026-09-18" (#556 and #557). They are marked active but have no effect; 63 posts on their list are
served as indexable. A trashed, inactive snippet "ACE temporary read-only robots diagnostic" (#564)
from this investigation can be emptied from the snippet trash.

## What is confirmed

| Fact | Source |
|---|---|
| Search Console > Manual actions: "No issues detected" | Site owner, 2026-11-26 |
| US ranking keywords: between 5 and 30 every month from May 2025 to March 2026, none better than position 31. A brief rise to about 100 in April-May 2026 (still none in the top 30), then 37 (June), 7 (July), 0 (August to November) | DataforSEO history, 2026-11-25 |
| Google impressions Nov 12-25: 19 in total, 0 clicks. 9 of them were someone searching `site:gearuptofit.com` | Search Console via Supermetrics, 2026-11-26 |
| A `site:gearuptofit.com` search returns the homepage only | Live Google result, 2026-11-25 |
| Google downloaded `sitemap_index.xml` on 2026-11-26 with no errors or warnings (1,262 URLs submitted) | Search Console sitemaps report |
| Pages load (HTTP 200), canonicals point to themselves, no noindex tag or header, robots.txt allows crawling | Crawl of all 801 sitemap URLs |
| Googlebot's user agent is served byte-for-byte the same HTML as a browser on 6 sampled URLs | Direct comparison, 2026-11-26. A check from Google's own IP range is not possible from here |
| 839 of the site's 1,350 posts were set to noindex on 2026-09-18 (posts with no clicks and under 50 impressions in 16 months) | Active code snippet "PGCC gearuptofit prune noindex" |
| `watch-match` is the largest section: 273 of 801 indexable URLs. 259 of its 272 crawled pages share half or more of their text with another page (two template groups of 177 and 78) | Engine audit, `reports/2026-11-26/summary.md` |
| The 498 remaining posts are not templated: 8 flagged, typical overlap with the closest other post 6% | Engine audit |

## What this rules out

- A crawl block, a stray noindex, a canonical error or a broken sitemap. None exists.
- Serving different content to Google by user agent.

## Plan

1. Done 2026-11-26: the three earning posts were released from the theme's prune list.
2. Done 2026-11-26: the IndexNow key file was fixed and 804 pages were submitted (see `docs/indexnow.md`).
3. **Find out which search engines send the 638 visits.** The Analytics pull for this is scheduled.
4. **Feed Analytics into every weekly run** (`data/ga4/<domain>/`), so the engine ranks and protects
   pages by real visitors, and add an Analytics check to the prune scripts.
5. **Leave Google recovery as a slow track.** No bulk rewrites or re-dating of posts.
