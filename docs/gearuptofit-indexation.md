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

## Earning pages that are set to noindex

These pages produced Amazon clicks in the last 14 days and carry `noindex, follow` on the live page:

| Page | Amazon clicks |
|---|---|
| /review/best-treadmills-for-home/ | 4 |
| /review/best-compression-boots/ | 3 |
| /review/best-running-shoes-for-heavy-runners/ | 1 |
| /shoe-finder/shoes/topo-ultrafly-6/ | 4 |

WordPress itself reports all three review posts as indexable, and only one of them
(best-compression-boots) is in the September prune list. The noindex tag is added by whatever serves
the review pages to visitors, which is not WordPress (the responses carry no WordPress headers). That
layer cannot be read or changed with the WordPress login, so this fix has to be made there.
Search engines that still list these pages will drop them while the tag stays.

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

1. **Remove the noindex tag from the earning pages above**, in the layer that serves them.
2. **Find out which search engines send the 638 visits**, then register the site with that engine's
   webmaster tools so its indexing and queries are visible. The Analytics pull for this is scheduled.
3. **Feed Analytics into every weekly run** (`data/ga4/<domain>/`), so the engine ranks and protects
   pages by real visitors.
4. **Clean up overlapping automation.** Two active copies of the prune snippet and five active copies
   of the Amazon link snippet run on every page load. Keep one of each. Do not edit the prune snippets
   casually: both copies define the same function, and re-saving one may deactivate it and make all
   837 pruned posts indexable at once.
5. **Leave Google recovery as a slow track.** No bulk rewrites or re-dating of posts.
