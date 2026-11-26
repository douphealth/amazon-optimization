# Submitting pages to search engines (IndexNow)

`python -m ace submit` tells Bing, Yandex, Seznam, Naver and the engines that use Bing's index which
pages are new or changed. Google does not take part in IndexNow. Analytics shows the portfolio's
search visitors come mostly from engines other than Google, so this is the submission that matters.

- Dry run by default; `--apply` sends. The key comes from the `INDEXNOW_KEY` environment variable.
- Only indexable pages are sent: they load, are not noindex, and are their own canonical.
- The first run sends every such page once. Later runs send only pages whose title or text changed.
  State is kept in `data/indexnow/<domain>.json`.
- Before sending, the engine checks that `https://<host>/<key>.txt` returns the key. If not, it
  refuses, because the engines would reject the submission.

## Status on 2026-11-26

| Site | Result |
|---|---|
| efficientgptprompts.com | 491 pages submitted, accepted |
| mysticaldigits.com | 474 pages submitted, accepted |
| gearuptogrow.com | 109 pages submitted, accepted |
| gearuptofit.com | Blocked: key file returns a different key (801 pages waiting) |
| plantastichaven.com | Blocked: key file returns a different key (160 pages waiting) |
| frenchyfab.com | Blocked: key file returns a different key (161 pages waiting) |
| micegoneguide.com | Blocked: key file returns a different key (46 pages waiting) |
| affiliatemarketingforsuccess.com | Blocked: no key file route (120 pages waiting) |
| www.outdoormisting.com | Blocked: no key file route (21 pages waiting) |

## Why six sites are blocked, and the fix

The Cloudflare Worker `portfolio-indexnow-key` serves the key file. It returns one hard-coded key
for every route, but on most sites the route is a file named after a second key, so name and content
disagree. `infra/indexnow-key-worker.js` is a corrected version that answers with the key named in
the URL. Deploy it over the existing Worker, add a route on the two sites that have none, then run
`python -m ace submit --apply`; the waiting pages go out on that run.

For the weekly GitHub run, add the key as the repository secret `INDEXNOW_KEY`.
