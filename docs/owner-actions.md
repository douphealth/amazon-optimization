# Owner actions: what only the owner can do

Everything else is automated. These steps need the owner's own logins; this session's GitHub
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

## 4. Dashboard sign-in: done, two optional clean-ups

Email-code sign-in is live at the `commission-engine` Worker's workers.dev address (Cloudflare >
Workers & Pages > commission-engine; the deploy script prints it): enter your email,
Cloudflare emails a 6-digit code, and the browser stays signed in for 30 days. It runs on the
Cloudflare account that holds your Zero Trust team, reuses its One-time PIN login, and allows the
address your existing Access policy already allows. To allow another address: Zero Trust > Access >
Applications > Commission Engine dashboard > Policies > Owner email addresses.

The Pages project (https://amazon-optimization.pages.dev) stays the dashboard's origin. Opening it
sends you to the email-code page; it never shows a password box (its `GATEWAY_URL` variable). The Pages project lives on a different Cloudflare account from the Zero Trust team,
and Cloudflare would not link the repository to a second account, so the email-code address is a
Worker in front of it (`infra/gateway/worker.js`, deployed by `infra/deploy_gateway.py`).

Optional, only you can do these (this session was not allowed to delete them):

1. The eight deployments made before the password was added are still reachable at their own
   addresses (`<id>.amazon-optimization.pages.dev`). Cloudflare (the account with the Pages project)
   > Workers & Pages > amazon-optimization > Deployments > for each deployment older than the
   password commit: ... > Delete deployment.
2. If you change the `DASHBOARD_PASSWORD` secret on the Pages project, run
   `python infra/deploy_gateway.py --owner-emails` again with the new password, or the email-code
   address answers "update the DASHBOARD_PASSWORD secret".

`infra/setup_access.py` (protecting the Pages address directly with Access) stays for the day the
Pages project and the Zero Trust team are on the same account.

## 5. Make the repository private

The repository holds Search Console queries, Analytics numbers and every page's index status. While
it is public, anyone can read them. GitHub > douphealth/amazon-optimization > Settings > General >
Danger Zone > Change repository visibility > Private. Nothing else needs to change: the weekly run
and the Cloudflare Pages deployment keep working, and the dashboard then shows the last run from the
record each run commits (`data/last-run.json`) instead of asking GitHub live. To undo, change it
back to Public in the same place.
