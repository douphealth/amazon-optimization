# Owner actions: what only the owner can do

Everything else is automated. These five steps need the owner's own logins; this session's GitHub
access is not allowed to change repository settings or Actions secrets.

## 1. Add the repository secrets (5 minutes, once)

The weekly run pulls Search Console, Bing and Analytics data, applies the switched-on fixes and
submits changed pages only when these secrets exist. They are skipped, not failed, until then.

GitHub > douphealth/amazon-optimization > Settings > Secrets and variables > Actions > New
repository secret:

| Secret | Switches on |
|---|---|
| `GSC_SERVICE_ACCOUNT_JSON` | Search Console (pages, queries, daily trend, sitemaps, URL Inspection) and Google Analytics |
| `BING_API_KEY` | Bing Webmaster clicks, impressions, queries and crawl errors |
| `INDEXNOW_KEY` | Submitting new and changed pages to Bing and the other IndexNow engines |
| `WP_AUTH_<SITE>` (one per WordPress site) | The fixes switched on in `sites.yaml`, every Monday |

The exact values were prepared in a private file in the working session, with a one-command upload
(`gh secret set -f ... -R douphealth/amazon-optimization`). This session's GitHub access cannot
write Actions secrets: the connection blocks it on purpose.

## 2. Let the engine read two Analytics properties

The live tags on these sites send data to properties the service account cannot read:

| Site | Tag on the site | What to do |
|---|---|---|
| FrenchyFab | `G-K8XBLM8WGT` | In Google Analytics, find the property whose web stream has this measurement ID, then Admin > Property access management > add the service account as Viewer |
| Efficient GPT Prompts | `G-1JL0RGYKZ4` | Same |

The service account's email is in the Search Console key (`client_email`). The next run finds the
right property by itself; no change to `sites.yaml` is needed.

## 3. Put the Analytics tag on Plantastic Haven

The site loads no Google Analytics tag, so its visits and Amazon clicks go unrecorded (22 sessions
in four weeks against 209 search clicks). WordPress admin > Settings > Header and Footer Scripts >
Scripts in header, paste:

```
<script async src="https://www.googletagmanager.com/gtag/js?id=G-NP9KW420V3"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-NP9KW420V3');
</script>
```

`G-NP9KW420V3` is the measurement ID of Plantastic Haven's Analytics property (378647208). Then
purge the LiteSpeed and Seraphinite caches so cached pages pick it up. The engine could not do this
safely itself: no WordPress API exposes the header-scripts setting, and switching on the inactive
snippet plugins could re-run old stored code.

## 4. Dashboard sign-in: switch to email codes

Today the dashboard asks for a password (any user name; the password is the `DASHBOARD_PASSWORD`
secret in the Cloudflare Pages project and was handed over privately). Everything for sign-in by
email code is built and tested; it needs one Cloudflare token that this session was not allowed to
create itself:

1. Cloudflare (the account that holds the `amazon-optimization` Pages project) > My Profile > API
   Tokens > Create Token > Create Custom Token.
2. Permissions: *Account · Access: Apps and Policies · Edit* and *Account · Access: Organizations,
   Identity Providers, and Groups · Edit*. Account Resources: that account. An expiry of one day is
   enough.
3. If Cloudflare has never shown this account the Zero Trust section, open Zero Trust once and pick
   a team name and the Free plan (free for up to 50 users).
4. Hand the token over (upload it to the session), or run it yourself:
   `CF_ACCESS_TOKEN=... CF_PAGES_TOKEN=... python infra/setup_access.py you@example.com`

The script switches on the email code, protects the dashboard and every per-deployment address
(`*.amazon-optimization.pages.dev`, which also closes off the deployments made before the password),
allows only the addresses given, and switches the dashboard's own check to verify Cloudflare's
signed sign-in token, so the password stops working. You then stay signed in for 30 days per
browser. To allow another address later, add it under Zero Trust > Access > Applications >
Commission Engine dashboard > Policies.

## 5. Make the repository private

The repository holds Search Console queries, Analytics numbers and every page's index status. While
it is public, anyone can read them. GitHub > douphealth/amazon-optimization > Settings > General >
Danger Zone > Change repository visibility > Private. Nothing else needs to change: the weekly run
and the Cloudflare Pages deployment keep working, and the dashboard then shows the last run from the
record each run commits (`data/last-run.json`) instead of asking GitHub live. To undo, change it
back to Public in the same place.
