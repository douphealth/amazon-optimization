# GearUpToFit: why Google shows almost none of it

Status on 2026-11-26. GearUpToFit holds 2,012 of the portfolio's 3,161 Amazon links and gets no
Google traffic, so this is the largest commission problem in the portfolio.

**Decision on 2026-11-26: do not noindex `watch-match` yet.** The owner confirmed there is no manual
action. Re-reading the ranking history shows the site was already close to invisible a year before
`watch-match` existed, so it cannot be the original cause. The next step is the Page indexing
breakdown from Search Console; the plan below starts only after that.

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

## What the evidence now says

- **This is an automated, site-wide demotion, and it is old.** With no manual action and no technical
  block, Google is choosing not to index or rank the site. It was already doing so in May 2025, the
  earliest month in the data. What first caused it is not visible from here.
- **`watch-match` is not the original cause.** Its integration notes are dated June 2026, a year after
  the site was already near zero. It may still weigh on the site (a third of the indexable pages are
  templated), but removing it is unlikely to bring the site back by itself.
- **The September prune has not helped so far.** 839 posts went to noindex on 2026-09-18 and
  visibility has not returned in the two months since.

Recovery from this kind of demotion is slow and uncertain. It should be treated as a months-long
project, and near-term commission work should go to the sites and traffic sources that already
produce Amazon clicks.

## The check still open

Page indexing, while signed in to Search Console:
https://search.google.com/search-console/index?resource_id=sc-domain%3Agearuptofit.com

A screenshot of the "Why pages aren't indexed" table is enough. The counts next to "Crawled -
currently not indexed", "Discovered - currently not indexed", "Excluded by noindex tag" and any
"Blocked" or "Server error" rows decide which step below comes first.

## Plan once that answer is in

In this order, one change at a time so each can be measured. If the table shows "Blocked" or
"Server error" rows in volume, fix that first: it would mean Google's crawler is being turned away
in a way a test from here cannot see.

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
