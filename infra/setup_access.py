"""Put the dashboard behind Cloudflare Access with email-code sign-in (One-time PIN).

After this runs, opening the dashboard shows Cloudflare's sign-in page: enter an allowed email
address, Cloudflare emails a 6-digit code, enter it, and the browser stays signed in for 30 days.
The dashboard's own check (functions/_middleware.js) then verifies Access's signed token on every
request, so the old password stops working.

Usage (tokens only from the environment, typed so they stay out of shell history):

    read -rs CF_ACCESS_TOKEN && export CF_ACCESS_TOKEN
    python infra/setup_access.py you@example.com [other@example.com]

    python infra/setup_access.py --rollback      back to the password sign-in

CF_ACCESS_TOKEN  an API token for the account that owns the Pages project, with
                 "Access: Apps and Policies Edit",
                 "Access: Organizations, Identity Providers, and Groups Edit" and
                 "Cloudflare Pages Edit"
CF_PAGES_TOKEN   optional: a separate token with "Cloudflare Pages Edit" on the same account

Order of work, so there is never a moment without a sign-in and the owner is never locked out:
team, email-code login, application (dashboard + every per-deployment address), allowed
addresses; then it confirms that Cloudflare really answers the dashboard with the sign-in page;
only then does it switch the dashboard's own check to Access and redeploy. A re-run replaces the
allowed addresses with the ones given.
CF_ACCOUNT_ID    default: the account that hosts amazon-optimization
PAGES_PROJECT    default: amazon-optimization
ACCESS_TEAM      only needed when the account has never used Zero Trust: the team name to create
                 (becomes <team>.cloudflareaccess.com)

Safe to run again: it reuses what already exists and only adds what is missing.
"""
from __future__ import annotations

import os
import sys
import time

import requests

PAGE = 100

API = "https://api.cloudflare.com/client/v4"
APP_NAME = "Commission Engine dashboard"
SESSION = "720h"  # 30 days between codes


class CloudflareError(RuntimeError):
    pass


class Client:
    def __init__(self, token: str, account: str, session=None):
        self.base = f"{API}/accounts/{account}"
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def call(self, method: str, path: str, **kw):
        resp = self.session.request(method, self.base + path, headers=self.headers, timeout=60, **kw)
        try:
            body = resp.json()
        except ValueError:
            raise CloudflareError(f"{method} {path}: HTTP {resp.status_code}")
        if not body.get("success"):
            errors = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in body.get("errors", []))
            raise CloudflareError(f"{method} {path}: {errors or 'HTTP ' + str(resp.status_code)}")
        return body.get("result")


def list_all(client: Client, path: str) -> list:
    """Every item of a paginated list endpoint."""
    items, page = [], 1
    while True:
        batch = client.call("GET", path, params={"page": page, "per_page": PAGE}) or []
        items += batch
        if len(batch) < PAGE:
            return items
        page += 1


def covers(app: dict, host: str) -> bool:
    """Whether the application protects the host and every per-deployment address."""
    names = {d.get("uri") for d in app.get("destinations") or []} | set(app.get("self_hosted_domains") or []) | {app.get("domain")}
    return host in names and f"*.{host}" in names


def ensure_organization(access: Client, team: str | None, log=print) -> str:
    """The Zero Trust team domain (<team>.cloudflareaccess.com); created when missing and a team is given."""
    try:
        org = access.call("GET", "/access/organizations")
        if org and org.get("auth_domain"):
            log(f"Zero Trust team: {org['auth_domain']}")
            return org["auth_domain"]
    except CloudflareError as exc:
        if not team:
            raise CloudflareError(f"{exc}. If this account has never used Zero Trust, set ACCESS_TEAM to a team name "
                                  "(or open Cloudflare > Zero Trust once and pick the Free plan).")
    if not team:
        raise CloudflareError("This account has no Zero Trust team yet: set ACCESS_TEAM to a team name.")
    org = access.call("POST", "/access/organizations", json={"name": team, "auth_domain": f"{team}.cloudflareaccess.com"})
    log(f"Zero Trust team created: {org['auth_domain']}")
    return org["auth_domain"]


def ensure_otp(access: Client, log=print) -> str:
    for idp in access.call("GET", "/access/identity_providers") or []:
        if idp.get("type") == "onetimepin":
            log("Email code sign-in (One-time PIN): already on")
            return idp["id"]
    idp = access.call("POST", "/access/identity_providers", json={"name": "Email code", "type": "onetimepin", "config": {}})
    log("Email code sign-in (One-time PIN): switched on")
    return idp["id"]


def ensure_app(access: Client, host: str, otp_id: str, log=print) -> dict:
    """A self-hosted Access application covering the dashboard and every per-deployment address."""
    wildcard = f"*.{host}"
    body = {
        "name": APP_NAME, "type": "self_hosted", "domain": host,
        "destinations": [{"type": "public", "uri": host}, {"type": "public", "uri": wildcard}],
        "session_duration": SESSION, "allowed_idps": [otp_id], "auto_redirect_to_identity": True,
        "app_launcher_visible": False,
    }
    find = lambda: next((a for a in list_all(access, "/access/apps") if a.get("domain") in (host, wildcard)
                         or {host, wildcard} & {d.get("uri") for d in a.get("destinations") or []}), None)
    existing = find()
    if existing:
        app = access.call("PUT", f"/access/apps/{existing['id']}", json=body)
        log(f"Access application updated: {APP_NAME}")
    else:
        try:
            app = access.call("POST", "/access/apps", json=body)
        except CloudflareError as first:
            if "destination" not in str(first).lower():
                raise
            app = find()  # never create a second application for the same addresses
            legacy = {k: v for k, v in body.items() if k != "destinations"} | {"self_hosted_domains": [host, wildcard]}
            app = access.call("PUT", f"/access/apps/{app['id']}", json=legacy) if app else access.call("POST", "/access/apps", json=legacy)
        log(f"Access application created: {APP_NAME} for {host} and {wildcard}")
    if not covers(app, host):
        raise CloudflareError(f"the application does not list both {host} and {wildcard}; nothing was switched over")
    return app


def ensure_policy(access: Client, app_id: str, emails: list[str], log=print) -> None:
    include = [{"email": {"email": e}} for e in emails]
    current = access.call("GET", f"/access/apps/{app_id}/policies") or []
    mine = next((p for p in current if p.get("name") == "Owner email addresses"), None)
    others = [p for p in current if p is not mine]
    for p in others:
        log(f"Note: the application also has the policy '{p.get('name')}' ({p.get('decision')}), which this script leaves alone")
    if mine:
        body = {"name": mine["name"], "decision": "allow", "include": include, "precedence": mine.get("precedence", 1)}
        access.call("PUT", f"/access/apps/{app_id}/policies/{mine['id']}", json=body)
        log(f"Allowed addresses replaced: {len(emails)}")
    else:
        precedence = max([p.get("precedence", 0) for p in others] + [0]) + 1
        access.call("POST", f"/access/apps/{app_id}/policies",
                    json={"name": "Owner email addresses", "decision": "allow", "include": include, "precedence": precedence})
        log(f"Allowed addresses set: {len(emails)}")


def access_enforced(host: str, team_domain: str, get=requests.get, wait: int = 180, log=print) -> bool:
    """True once Cloudflare answers the dashboard with the Access sign-in page instead of the site."""
    deadline = time.time() + wait
    while True:
        try:
            resp = get(f"https://{host}/", allow_redirects=False, timeout=30)
            if resp.status_code in (302, 303) and team_domain in resp.headers.get("Location", "") and "/cdn-cgi/access/login" in resp.headers.get("Location", ""):
                log(f"Confirmed: {host} now answers with the email-code sign-in page")
                return True
        except requests.RequestException:
            pass
        if time.time() > deadline:
            return False
        time.sleep(10)


def _redeploy(pages: Client, project: str) -> str:
    latest = pages.call("GET", f"/pages/projects/{project}/deployments", params={"per_page": 1, "env": "production"})[0]
    deployment = pages.call("POST", f"/pages/projects/{project}/deployments/{latest['id']}/retry")
    for _ in range(60):
        state = pages.call("GET", f"/pages/projects/{project}/deployments/{deployment['id']}")
        stage = state.get("latest_stage", {})
        if stage.get("status") in ("failure", "canceled") or (stage.get("name") == "deploy" and stage.get("status") == "success"):
            return f"{stage.get('status')} ({state.get('url', '')})"
        time.sleep(10)
    return f"still running ({deployment.get('url', '')})"


def switch_dashboard(pages: Client, project: str, team_domain: str, aud: str, log=print) -> str:
    """Tell the dashboard's sign-in check to require Access, then redeploy so it takes effect."""
    variables = {"ACCESS_TEAM_DOMAIN": {"type": "plain_text", "value": team_domain}, "ACCESS_AUD": {"type": "plain_text", "value": aud}}
    pages.call("PATCH", f"/pages/projects/{project}",
               json={"deployment_configs": {env: {"env_vars": variables, "fail_open": False} for env in ("production", "preview")}})
    log("Dashboard switched to email-code sign-in; redeploying")
    return _redeploy(pages, project)


def rollback(pages: Client, project: str, log=print) -> str:
    """Back to the password sign-in: remove the two Access variables and redeploy. The Access
    application stays (delete it in Zero Trust > Access > Applications if no longer wanted)."""
    variables = {"ACCESS_TEAM_DOMAIN": None, "ACCESS_AUD": None}
    pages.call("PATCH", f"/pages/projects/{project}", json={"deployment_configs": {env: {"env_vars": variables} for env in ("production", "preview")}})
    log("Access variables removed; redeploying with the password sign-in")
    return _redeploy(pages, project)


def main(argv: list[str]) -> int:
    account = os.environ.get("CF_ACCOUNT_ID", "284f1a03e12aa7416ab177db3f692c17")
    project = os.environ.get("PAGES_PROJECT", "amazon-optimization")
    host = f"{project}.pages.dev"
    pages_token = os.environ.get("CF_PAGES_TOKEN") or os.environ.get("CF_ACCESS_TOKEN")
    if not pages_token:
        print(__doc__)
        return 2
    pages = Client(pages_token, account)
    if "--rollback" in argv:
        print(f"Deployment: {rollback(pages, project)}")
        return 0
    emails = [a.strip().lower() for a in argv if "@" in a]
    if not emails or not os.environ.get("CF_ACCESS_TOKEN"):
        print(__doc__)
        return 2
    access = Client(os.environ["CF_ACCESS_TOKEN"], account)
    pages.call("GET", f"/pages/projects/{project}")  # fail now, before changing anything, if the Pages token is wrong
    team_domain = ensure_organization(access, os.environ.get("ACCESS_TEAM"))
    otp_id = ensure_otp(access)
    app = ensure_app(access, host, otp_id)
    try:
        ensure_policy(access, app["id"], emails)
    except CloudflareError as exc:
        print(f"Setting the allowed addresses failed ({exc}). Access now blocks everyone, including you. "
              "Run this script again, or add your address under Zero Trust > Access > Applications > "
              f"{APP_NAME} > Policies, or delete that application to reopen the password sign-in.")
        return 1
    if not access_enforced(host, team_domain):
        print(f"Cloudflare does not yet answer {host} with the sign-in page, so the dashboard was NOT switched over "
              "(it keeps the password sign-in behind Access). Run this script again in a few minutes.")
        return 1
    result = switch_dashboard(pages, project, team_domain, app["aud"])
    print(f"Deployment: {result}. Open https://{host}/ : enter your email, Cloudflare sends a 6-digit code. "
          "To undo: python infra/setup_access.py --rollback")
    return 0 if result.startswith("success") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
