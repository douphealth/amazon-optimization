# Amazon Commission Engine

Finds where a portfolio of content sites loses Amazon Associates commission, ranks the pages by
how many Amazon clicks they waste, and drafts the fixes.

It crawls every URL in each site's sitemaps, reads every Amazon link, joins that with Search
Console data, and writes one report. It never changes a website: every fix is a draft file.

## What one run produces

`python -m ace run` writes to `reports/<date>/`:

| File | What it is |
|---|---|
| `summary.md` | Portfolio table, what changed since the last run, per-site problems, the ranked work queue, title-rewrite candidates, indexation signals |
| `pages.csv` | One row per page: Amazon link counts, how deep the first link sits, tags, issues, score |
| `links.csv` | One row per Amazon link: product ID, tracking ID, link type, product name |
| `fixes/<site>/<page>.html` | Paste-ready "quick picks" box for pages whose links sit too deep |
| `indexnow-log.csv` | What `ace submit` sent to search engines, per site |

## Dashboard

`python -m ace site` turns the latest report into a static dashboard: one page of HTML, one
stylesheet, one script, `data.json` and `links.json`. No framework and no files loaded from other
servers. Light and dark themes; works on a phone.

| View | What it shows |
|---|---|
| Overview | A briefing written from the data, the engine's last and next run, totals with the change since the previous report (trend lines once three reports exist), what needs a decision, what changed, the pages sending most people to Amazon, one card per site |
| Work queue | Pages where measured demand meets a gap in Amazon links, highest priority first. Tick pages off as you handle them (kept in your browser); pages the engine fixed are ticked for you |
| Findings | Every check across all sites: pages affected, change since the last report, sites affected, and whether the engine fixes it on its own, could but is switched off, or leaves it to you |
| Pages | Every audited page: search, one-click filters per finding, sort by any column, export or copy the filtered list |
| Site | Where the first Amazon link sits, findings with their change, tracking IDs in use, submissions, the pages to work on first, changes the engine made |
| Activity | Engine runs (live from GitHub), page changes (live, or saved but not visible) and submissions to search engines |
| Notes | The full report and the files in `docs/` |
| Controls | Links into this repository on GitHub: run the engine, edit `sites.yaml`, add a product box, upload data, manage secrets, browse past reports |

Selecting any page opens its detail panel: numbers, each finding with what to do and who handles
it, the product box written or drafted for it, and every Amazon link in the article with its
tracking ID. `Ctrl K` (or `/`) opens a search over pages, sites, findings and actions.

The dashboard is read-only. It cannot hold logins, so every action opens the real control in
GitHub; `repository` in `sites.yaml` tells it where that is. The run status is the one live call it
makes, to GitHub's public API, and it only works while the repository is public.

`package.json` exists only so a static host such as Cloudflare Pages can build it: the build command
is `npm run build`, and the site is written to `dist/` (copies go to `build/`, `public/`, `out/`,
`_site/` and the project root, so the host's output-folder setting does not matter). The build reads
files in the repository only; it never crawls. Every push, including the weekly audit's, republishes
it. The pages ask search engines not to index them, but the address is public unless the host
restricts access (on Cloudflare: Zero Trust > Access > add an application for the Pages address).

## What it checks on every page

- No Amazon link at all, or the first link sits in the bottom half of the article
- Links with no tracking tag (earn nothing), with a foreign tag, or with a tracking ID that isn't the site's
- `amzn.to` short links (the tag can't be audited)
- Pages that only use Amazon search links instead of product links
- Missing `rel="sponsored"`, missing OneLink script, noindex, wrong canonical, missing meta description
- With Search Console data: pages Google shows on page 1 that almost nobody clicks
- With Google Analytics data: the pages that actually produce Amazon clicks, and whether each is
  indexable, in a sitemap and well linked
- Pages with Amazon links and no affiliate statement of any kind, and sites where the exact
  Amazon Associates statement appears nowhere
- Indexation signals per sitemap: thin pages, pages that share half or more of their text with
  another page (templated or programmatic content), duplicate titles, redirects in the sitemap
- Every run after the first: what changed since the previous report, including pages that
  lost their Amazon links

## Latest run: 2026-11-26

2,384 pages on 9 sites, 3,161 Amazon links. Full detail in `reports/2026-11-26/summary.md`.

| Priority | Finding | Fix |
|---|---|---|
| 1 | **GearUpToFit gets no Google traffic but is still the main source of Amazon clicks.** Google Analytics shows 638 organic-search visits in 14 days (from engines other than Google) and 63 of the portfolio's 66 recorded Amazon clicks. Google itself has crawled the site and indexed 1 page of 702. Three review pages that produce Amazon clicks had been set to noindex by the prune list in the child theme's `functions.php` | Fixed 2026-11-26: the three posts were released and are indexable, in the sitemap and submitted. See `docs/gearuptofit-indexation.md`. Do not noindex `watch-match` |
| 2 | **Every WordPress site except Plantastic Haven rewrites Amazon links when the page is rendered.** Code snippets named "Hermes Portfolio Amazon Product Box OS v1" force a tracking ID on every Amazon link and "PGCC Amazon disclosure" adds a disclosure. Editing a post body there does not change the tracking ID on the live page (verified on one Mystical Digits post) | Change tracking IDs in those snippets, not in posts. On GearUpToFit, Mice Gone Guide and Efficient GPT Prompts the snippet is set to the bare `papalex-20` |
| 3 | **582 live links use the bare `papalex-20` ID**: 512 on GearUpToFit `watch-match` pages and 57 on Efficient GPT Prompts. Their clicks can't be told apart in Associates reports | `watch-match` is a separate app; Efficient GPT Prompts needs its own tracking ID created in Associates Central first |
| 4 | **Outdoor Misting has one untagged Amazon link** (`/comparing-outdoor-cooling-technologies/`, product B0BFGL8FBZ) and no affiliate statement on that page. The site is not WordPress, so the fixer cannot reach it | Add a tracking ID and a disclosure in the site's own code |
| 5 | **Plantastic Haven: about 40 pages have their first Amazon link in the bottom half**, 53 have none, 24 use only search links | Hand-written boxes went live on the four pages with the most Google traffic on 2026-11-26 (see below) |
| 6 | **No site loads Amazon OneLink**, so non-US visitors land on amazon.com | Join the regional programs and add the OneLink script |

**Correction (2026-11-26):** earlier reports said 165 GearUpToFit posts had no Amazon disclosure. That was a
false alarm. The check looked only for the exact words "As an Amazon Associate"; those pages carry
plain-language affiliate disclosures near the top. The check now accepts such statements, and 2 pages
in the whole portfolio remain flagged. Because the check changed, the "-165" in that report's change
table reflects the corrected check, not a fix.

Two domains from Search Console were dropped from `sites.yaml`: `shocksensors.com` is a parked
page and `webmarketingbooks.com` now shows an unrelated business.

## The fixer

`python -m ace fix` plans edits from the latest audit and shows what it would change.
`python -m ace fix --apply` saves them through the WordPress REST API.

- It edits only the post body, keeps a copy in `backups/` (not committed), relies on WordPress
  revisions for rollback, and re-audits the live page after every save.
- `auto_fix` in `sites.yaml` lists the fixes it may make. Today that is `rel`, `blocked` and `box`.
  `tags` and `disclosure` are off: by decision on 2026-11-26 the render-time snippets above own
  tracking IDs and disclosures, and this engine owns boxes, link attributes and blocked products.
- A generated box is used only on pages with Google clicks and only where a safe spot exists.
  A hand-written box in `boxes/<domain>/<url-slug>.html` overrides it and can name its own spot
  with a first line such as `<!-- place-after: </nav> -->`.
- Logins are WordPress Application Passwords in environment variables named `WP_AUTH_<DOMAIN>`
  (for example `WP_AUTH_PLANTASTICHAVEN_COM="user:xxxx xxxx xxxx xxxx xxxx xxxx"`). Never commit them.

Changes made to live sites so far (`reports/2026-11-26/fix-log.csv`):

| Date | Page | Change | Result on the live page |
|---|---|---|---|
| 2026-11-26 | plantastichaven.com/dripping-water-in-philodendron-plants/ | Product box after the quick answer | Live |
| 2026-11-26 | plantastichaven.com/how-cold-can-philodendron-tolerate/ | Product box after the quick answer | Live |
| 2026-11-26 | plantastichaven.com/string-of-pearls-plant-care/ | Product box before the first heading (the page had no Amazon links) | Live |
| 2026-11-26 | plantastichaven.com/plants-that-look-like-spider-plants/ | Product box after the at-a-glance list | Live |
| 2026-11-26 | 12 plantastichaven.com pages (listed in the fix log) | 22 links to a product that now shows plant food repointed to an Amazon search for potting mix | Live on all 12 |
| 2026-11-26 | plantastichaven.com/dripping-water-in-philodendron-plants/ | FAQ block moved out of the table of contents, where an earlier edit had put it inside a link | Live |
| 2026-11-26 | plantastichaven.com/string-of-pearls-plant-care/ | Title changed to match the search it shows for | Live (title and heading) |
| 2026-11-26 | plantastichaven.com/how-to-start-a-philodendron/ | Heading changed to match the search it shows for | Heading live; the search title needs pasting into Yoast |
| 2026-11-26 | gearuptofit.com: three review pages (treadmills, compression boots, shoes for heavy runners) | Released from the theme's prune list | Live: indexable, in the sitemap, submitted |
| 2026-11-26 | mysticaldigits.com/challenge-numbers-overcome/ | Tracking ID in the post body changed to `papalex-md-20` | No effect: a render-time layer still outputs `papalex-20` |

## Run it

```bash
pip install -r requirements.txt
python -m ace run                      # crawl + score + fix drafts, 1-3 minutes
python -m ace run --site plantastichaven.com
python -m ace rank --out reports/2026-11-26   # re-score a saved crawl after adding data (2 seconds)
python -m ace fix --apply             # save the safe fixes to WordPress
python -m ace submit --apply          # tell Bing and other engines about new and changed pages
python -m ace site                    # build the dashboard into dist/
python -m pytest -q
```

## Data it uses

**Search Console (decides the ranking).** Without it a page is audited but not ranked. Either:

- Export by hand: Search Console > Performance > Pages > Export, save as `data/gsc/<domain>/pages.csv`.
- Or automate: follow the three setup steps at the top of `ace/gsc.py`, then `python -m ace gsc-pull`.

The data in `data/gsc/` today is partial: 14 days (Nov 11–24, 2026), only pages with more than
60 impressions, for 5 sites.

**Google Analytics (shows traffic Google never sends).** Put `amazon_clicks.csv` (columns `page,amazon_clicks`)
and `sessions.csv` (columns `page,sessions`) in `data/ga4/<domain>/`. The audit then also crawls those
pages even when no sitemap lists them, ranks by real visitors, and flags any page that produces
Amazon clicks but is set to noindex. Today's files hold Nov 12-25, 2026, Amazon clicks only.

**Amazon Associates (optional, sharpens the ranking).** Download Reports > Tracking ID Summary as
CSV into `data/associates/`. Sites whose tracking ID earns more per click are then weighted higher.

## Weekly automation

`.github/workflows/weekly-audit.yml` runs every Monday, commits the new report, and pulls Search
Console data first if the `GSC_SERVICE_ACCOUNT_JSON` repository secret exists. It then runs the
fixer, but only on sites whose `WP_AUTH_<DOMAIN>` repository secret is set; with no secrets it
changes nothing. `docs/experiments.md` records each live change with its baseline.
`.github/workflows/tests.yml` runs the unit tests on every push.

## What has and hasn't been tested

| Part | Status |
|---|---|
| Crawl, link audit, scoring, near-duplicate detection, reports, fix drafts | Run live on all 9 sites on 2026-11-25 and 2026-11-26; 34 unit tests pass |
| Fixer: product boxes | Applied to 4 live Plantastic Haven posts and confirmed on the rendered pages |
| Fixer: blocked-product links | Applied to 12 live Plantastic Haven posts and confirmed on the rendered pages |
| Search-engine submission (`ace submit`) | 2,386 pages sent for all 9 sites on 2026-11-26 and accepted; a repeat run sends only changed pages |
| Fixer: tracking IDs | Saved once on a live post; the save worked but a render-time layer overrode it |
| Fixer: rel and disclosure edits | Unit-tested and dry-run against live content. Not applied to a live site |
| Change tracking between reports | Unit-tested, and run live once (no changes between the two days) |
| Search Console CSV import | Tested with real data and with the Search Console export format |
| Search Console API pull (`gsc-pull`) | Unit-tested against a fake API only. Not yet run with a real service account |
| Associates CSV import | Unit-tested with a sample layout. Not yet run on a real Associates export |
| GitHub Actions: tests | Passed on GitHub on 2026-11-26 |
| GitHub Actions: weekly audit | Ran on GitHub on 2026-11-26: all 2,384 pages loaded, report committed in about 100 seconds. The fixer step ran with no login secrets, so it changed nothing there |

Not included: checking whether linked products are still in stock. Amazon answers automated
requests with a robot check, so a reliable check needs Amazon's own product API.

## How the score works

`score = reachable clicks × monetization gap × value weight` (see `ace/score.py`). Reachable
clicks is the larger of real Google clicks and impressions × a typical click-through rate for the
page's position. Those typical rates are an assumption, set in one table at the top of the file.
The score orders the work; it is not a revenue forecast.

## Safety

- The audit is read-only. Only `ace fix --apply` writes to a site, and only the fixes named in `auto_fix`.
- Fix drafts reuse only products already linked on that page, with that page's own tracking ID.
- This repository holds Search Console data and a list of each site's weaknesses, so it is best
  kept private. Never commit a service-account key.
