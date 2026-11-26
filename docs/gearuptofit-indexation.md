# GearUpToFit: why Google shows almost none of it

Status on 2026-11-26. GearUpToFit holds 2,012 of the portfolio's 3,161 Amazon links and gets no
Google traffic, so this is the largest commission problem in the portfolio.

## What is confirmed

| Fact | Source |
|---|---|
| US ranking keywords: 100 (May 2026), 37 (June), 7 (July), 0 (August to November) | DataforSEO history, 2026-11-25 |
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

## What it does not settle

Two explanations fit everything above. Only Search Console can tell them apart.

1. **A manual action.** Shown under Security & Manual Actions. A site-wide spam action usually
   removes the homepage too, and the homepage is still indexed, so this is the less likely one.
2. **An automated site-wide quality demotion.** Google keeps the homepage and stops indexing the rest.
   The templated `watch-match` section, a third of the indexable site, is the clearest trigger
   candidate. The September prune removed weak posts and visibility did not return in the two
   months since, which points at something the prune did not touch.

## The one check that cannot be done from here

Open both while signed in to Search Console:

- Manual actions: https://search.google.com/search-console/manual-actions?resource_id=sc-domain%3Agearuptofit.com
- Page indexing: https://search.google.com/search-console/index?resource_id=sc-domain%3Agearuptofit.com

Note the manual-action message if any, and the counts next to "Crawled - currently not indexed"
and "Excluded by noindex tag".

## Plan once that answer is in

**If a manual action is listed:** fix the reason it names, then file a reconsideration request.
Nothing else below should start first.

**If none is listed**, in this order, one change at a time so each can be measured:

1. **Take `watch-match` out of Google's view.** Add `noindex, follow` to its pages and remove
   `watch-match/sitemap.xml` from `sitemap_index.xml` and from Search Console. It is a separate
   app, not WordPress, so this needs access to that app's code. It is reversible (remove the tag),
   but Google takes weeks to react either way, so it needs an explicit go-ahead. Its 512 Amazon
   links currently earn nothing because the pages get no traffic.
2. **Clean up overlapping automation.** Two active copies of the prune snippet and five active
   copies of the Amazon link snippet run on every page load. Keep one of each.
3. **Wait 4 to 6 weeks and re-measure** with `python -m ace run` and the Search Console pull before
   changing anything else. Recovery from a site-wide demotion normally follows a later Google
   core update, not the change itself.

Not recommended: further bulk rewrites or re-dating of the 498 posts. They are not the pages the
evidence points at.
