# What Google, Bing and Analytics say (2026-11-27)

First pull straight from the Search Console, URL Inspection, Bing Webmaster and Google Analytics
APIs for all nine sites. Every figure below comes from those APIs; none is estimated.
Windows: Google 28 Oct to 24 Nov, Bing 23 Oct to 19 Nov, Analytics 29 Oct to 25 Nov 2026.

## Bing carries the portfolio; Google barely shows most sites

| Site | Google clicks | Bing clicks | In Google's index | Analytics organic sessions |
|---|---|---|---|---|
| GearUpToFit | 2 | 593 | 1 of 807 | 1,366 |
| Plantastic Haven | 188 | 21 | 152 of 160 | 0 (tag problem, see below) |
| Mice Gone Guide | 0 | 325 | 27 of 46 | 659 |
| FrenchyFab | 0 | 103 | 32 of 161 | no data (see below) |
| Efficient GPT Prompts | 8 | 36 | 66 of 491 | no data (see below) |
| Affiliate Marketing for Success | 4 | 33 | 1 of 120 | 170 |
| Outdoor Misting | 11 | 0 | 7 of 21 | not configured |
| Mystical Digits | 0 | 7 | 47 of 474 | 12 |
| GearUpToGrow | 5 | 3 | 38 of 109 | 18 |

Over four weeks Bing sent about 1,120 clicks and Google 218, and 188 of Google's came from Plantastic
Haven. Bing, Yahoo, DuckDuckGo and Ecosia all use Bing's index, so for most of these sites Bing
is where the Amazon clicks come from. The engine now ranks pages on Google and Bing together.

## Google has dropped GearUpToFit and Affiliate Marketing for Success

- **GearUpToFit:** Google has indexed 1 of 807 pages, the homepage. 655 pages are "URL is unknown to
  Google" and 151 are "Crawled - currently not indexed".
  - The sitemap is fine: submitted, read on 26 Nov, 1,262 URLs, no errors.
  - Google impressions were 5,696 in April 2026, 231 in May, and 34 so far in November.
  - Google has crawled only 152 of the 807 pages at all, and for 65 of those the latest crawl is from April 2026.
  - So Google stopped valuing the site around May 2026. This is not a technical block.
- **Affiliate Marketing for Success:** Google has indexed 1 of 120 pages (the homepage), with 37
  impressions in four weeks.
- **On both sites, people still want these pages.** 305 pages across the portfolio with demand
  (visits, Amazon clicks or 20+ Bing impressions) are not in Google's index, 218 of them on
  GearUpToFit.
  - Example: `/review/adidas-adizero-evo-sl-exo/`, 54 Bing clicks and 100 organic sessions, "Crawled - currently not indexed".
  - Example: `/health/supplements/best-supplements-for-increasing-muscle-mass-after-60/`, 60 Bing clicks and 5 Amazon clicks, unknown to Google.
  - The dashboard lists them all under the finding "Demand, not in Google".

## Some "not indexed" verdicts are out of date

135 pages, 132 of them on Efficient GPT Prompts, are listed by Google as "Excluded by 'noindex' tag"
or "Not found (404)", with a last crawl in May to September 2026. Today each of them loads and is
indexable. Google has simply not looked again. The fix is "Request indexing" in Search Console for
the pages that matter; the dashboard marks them "Google verdict out of date".

## Analytics is blind on three sites

- **Plantastic Haven:** Analytics recorded 22 sessions and no organic visits in four weeks, while Google
  and Bing report 209 clicks. The tag is missing on most pages or blocked by the consent banner.
- **FrenchyFab:** property 407291494 records no visits. The service account cannot read property
  409497113, which is probably the live one.
- **Efficient GPT Prompts:** property 546666742 records no visits.

Until these are fixed, those sites' pages are ranked on search data alone, and their Amazon clicks
are invisible.

## What the engine changed

Nothing on any website in this step. It only read data.
