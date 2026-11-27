# Owner actions: what only the owner can do

Everything else is automated. These four steps need the owner's own logins.

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

## 4. Dashboard sign-in

The dashboard at amazon-optimization.pages.dev asks for a password (any user name). The password is
the `DASHBOARD_PASSWORD` secret in the Cloudflare Pages project (account papalexios001, project
amazon-optimization, Settings > Variables and Secrets); it was handed over privately and is not in
this repository. To change it, edit that secret and redeploy.
