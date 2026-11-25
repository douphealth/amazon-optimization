# Amazon Commission Engine

Finds where a portfolio of content sites loses Amazon Associates commission, ranks the pages by
how many Amazon clicks they waste, and drafts the fixes.

It crawls every URL in each site's sitemaps, reads every Amazon link, joins that with Search
Console data, and writes one report. It never changes a website: every fix is a draft file.

## What one run produces

`python -m ace run` writes to `reports/<date>/`:

| File | What it is |
|---|---|
| `summary.md` | Portfolio table, per-site problems, the ranked work queue, title-rewrite candidates |
| `pages.csv` | One row per page: Amazon link counts, how deep the first link sits, tags, issues, score |
| `links.csv` | One row per Amazon link: product ID, tracking ID, link type, product name |
| `fixes/<site>/<page>.html` | Paste-ready "quick picks" box for pages whose links sit too deep |

## What it checks on every page

- No Amazon link at all, or the first link sits in the bottom half of the article
- Links with no tracking tag (earn nothing), with a foreign tag, or with a tracking ID that isn't the site's
- `amzn.to` short links (the tag can't be audited)
- Pages with Amazon links but no "As an Amazon Associate" disclosure
- Pages that only use Amazon search links instead of product links
- Missing `rel="sponsored"`, missing OneLink script, noindex, wrong canonical, missing meta description
- With Search Console data: pages Google shows on page 1 that almost nobody clicks

## First run: 2026-11-25

2,384 pages on 9 sites, 3,152 Amazon links. Full detail in `reports/2026-11-25/summary.md`.

| Priority | Finding | Fix |
|---|---|---|
| 1 | **GearUpToFit holds 2,012 of the 3,152 Amazon links and gets no Google traffic.** It ranked for 100 US keywords in May 2026 and none since August. No technical block was found | Check Search Console > Manual actions, then Pages > "Crawled, currently not indexed". The 272 programmatic `watch-match` pages are the first suspect |
| 2 | **165 GearUpToFit posts have Amazon links but no "As an Amazon Associate" disclosure.** Amazon requires it | Add one sitewide disclosure line above post content |
| 3 | **582 links use the bare `papalex-20` ID**: 512 on GearUpToFit `watch-match` pages and 57 on Efficient GPT Prompts. Their clicks can't be told apart in Associates reports | Switch them to the site's own tracking ID |
| 4 | **Outdoor Misting has one untagged Amazon link** (`/comparing-outdoor-cooling-technologies/`, product B0BFGL8FBZ). It earns nothing. The site's most-visited pages carry no Amazon links | Add a tracking ID to the link; add product links to the two pages Google already shows |
| 5 | **Plantastic Haven: 40 pages have their first Amazon link in the bottom half**, 54 have none, 24 use only search links | 11 fix drafts are in `reports/2026-11-25/fixes/`; hand-written versions for the top 5 pages are in `docs/` |
| 6 | **No site loads Amazon OneLink**, so non-US visitors land on amazon.com | Join the regional programs and add the OneLink script |

Two domains from Search Console were dropped from `sites.yaml`: `shocksensors.com` is a parked
page and `webmarketingbooks.com` now shows an unrelated business.

## Run it

```bash
pip install -r requirements.txt
python -m ace run                      # crawl + score + fix drafts, about 3 minutes
python -m ace run --site plantastichaven.com
python -m ace rank --out reports/2026-11-25   # re-score a saved crawl after adding data
python -m pytest -q
```

## Data it uses

**Search Console (decides the ranking).** Without it a page is audited but not ranked. Either:

- Export by hand: Search Console > Performance > Pages > Export, save as `data/gsc/<domain>/pages.csv`.
- Or automate: follow the three setup steps at the top of `ace/gsc.py`, then `python -m ace gsc-pull`.

The data in `data/gsc/` today is partial: 14 days (Nov 11–24, 2026), only pages with more than
60 impressions, for 5 sites.

**Amazon Associates (optional, sharpens the ranking).** Download Reports > Tracking ID Summary as
CSV into `data/associates/`. Sites whose tracking ID earns more per click are then weighted higher.

## Weekly automation

`.github/workflows/weekly-audit.yml` runs every Monday, commits the new report, and pulls Search
Console data first if the `GSC_SERVICE_ACCOUNT_JSON` repository secret exists.

## What has and hasn't been tested

| Part | Status |
|---|---|
| Crawl, link audit, scoring, reports, fix drafts | Run live on all 9 sites on 2026-11-25; 9 unit tests pass |
| Search Console CSV import | Tested with real data and with the Search Console export format |
| Search Console API pull (`gsc-pull`) | Unit-tested against a fake API only. Not yet run with a real service account |
| Associates CSV import | Unit-tested with a sample layout. Not yet run on a real Associates export |
| GitHub Actions workflow | File is valid YAML. Not yet run on GitHub. If Cloudflare challenges GitHub's servers, pages will show as failed in the report |

Not included: checking whether linked products are still in stock. Amazon answers automated
requests with a robot check, so a reliable check needs Amazon's own product API.

## How the score works

`score = reachable clicks × monetization gap × value weight` (see `ace/score.py`). Reachable
clicks is the larger of real Google clicks and impressions × a typical click-through rate for the
page's position. Those typical rates are an assumption, set in one table at the top of the file.
The score orders the work; it is not a revenue forecast.

## Safety

- Read-only against the websites. Nothing is published.
- Fix drafts reuse only products already linked on that page, with that page's own tracking ID.
- Keep this repository private: it holds Search Console data. Never commit a service-account key.
