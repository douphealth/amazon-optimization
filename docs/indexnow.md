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

## Status on 2026-11-26: all nine sites submitted

| Site | Pages submitted | Engine response |
|---|---|---|
| gearuptofit.com | 804 | accepted |
| efficientgptprompts.com | 491 | accepted |
| mysticaldigits.com | 474 | accepted |
| frenchyfab.com | 161 | accepted, key check pending |
| plantastichaven.com | 160 | accepted, key check pending |
| affiliatemarketingforsuccess.com | 120 | accepted |
| gearuptogrow.com | 109 | accepted |
| micegoneguide.com | 46 | accepted, key check pending |
| www.outdoormisting.com | 21 | accepted, key check pending |

"Key check pending" (HTTP 202) means the engine took the list and will fetch the key file itself.

## What was broken, and what was changed on Cloudflare

The Worker `portfolio-indexnow-key` serves the key file. It returned one hard-coded key for every
route, while most sites routed a file named after a second key to it, so file name and content
disagreed and the engines rejected submissions. Two sites had no key file at all.

Changes made on 2026-11-26:

1. The Worker was replaced with `infra/indexnow-key-worker.js`: it answers with the key named in the
   URL, for the portfolio's keys. The previous script is saved in the session backup.
2. One new key was added and routed on all nine sites, so a single `INDEXNOW_KEY` works everywhere.
   The two older keys keep working on the sites that already used them.
3. Key-file routes were added where they were missing (affiliatemarketingforsuccess.com,
   outdoormisting.com, and the second key on four sites).

An engine can refuse a key for a while after it has seen a wrong key file for that host. That
happened on gearuptofit.com; the new key was accepted on the next attempt.

## Weekly run

Add the new key as the repository secret `INDEXNOW_KEY`. The weekly workflow then submits pages that
are new or changed since the last run.
