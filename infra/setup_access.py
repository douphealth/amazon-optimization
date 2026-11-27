"""Put the dashboard behind Cloudflare Access with email-code sign-in (One-time PIN).

After this runs, opening the dashboard shows Cloudflare's sign-in page: enter an allowed email
address, Cloudflare emails a 6-digit code, enter it, and the browser stays signed in for 30 days.
The dashboard's own check (functions/_middleware.js) then verifies Access's signed token on every
request, so the old password stops working.

Usage (tokens only from the environment; nothing is written to disk):

    CF_ACCESS_TOKEN=...  CF_PAGES_TOKEN=...  python infra/setup_access.py you@example.com [other@example.com]

CF_ACCESS_TOKEN  an API token for the account that owns the Pages project, with
                 "Access: Apps and Policies Write" and
                 "Access: Organizations, Identity Providers, and Groups Write"
CF_PAGES_TOKEN   a token with "Pages Write" on the same account (may be the same token)
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
    existing = next((a for a in access.call("GET", "/access/apps") or [] if a.get("domain") in (host, wildcard)), None)
    if existing:
        app = access.call("PUT", f"/access/apps/{existing['id']}", json=body)
        log(f"Access application updated: {APP_NAME}")
    else:
        try:
            app = access.call("POST", "/access/apps", json=body)
        except CloudflareError:  # older API: no `destinations`
            legacy = {k: v for k, v in body.items() if k != "destinations"}
            app = access.call("POST", "/access/apps", json={**legacy, "self_hosted_domains": [host, wildcard]})
        log(f"Access application created: {APP_NAME} for {host} and {wildcard}")
    return app


def ensure_policy(access: Client, app_id: str, emails: list[str], log=print) -> None:
    include = [{"email": {"email": e}} for e in emails]
    body = {"name": "Owner email addresses", "decision": "allow", "include": include, "precedence": 1}
    existing = next((p for p in access.call("GET", f"/access/apps/{app_id}/policies") or [] if p.get("name") == body["name"]), None)
    if existing:
        access.call("PUT", f"/access/apps/{app_id}/policies/{existing['id']}", json=body)
        log(f"Allowed addresses updated: {len(emails)}")
    else:
        access.call("POST", f"/access/apps/{app_id}/policies", json=body)
        log(f"Allowed addresses set: {len(emails)}")


def switch_dashboard(pages: Client, project: str, team_domain: str, aud: str, log=print) -> str:
    """Tell the dashboard's sign-in check to require Access, then redeploy so it takes effect."""
    variables = {"ACCESS_TEAM_DOMAIN": {"type": "plain_text", "value": team_domain}, "ACCESS_AUD": {"type": "plain_text", "value": aud}}
    pages.call("PATCH", f"/pages/projects/{project}",
               json={"deployment_configs": {env: {"env_vars": variables} for env in ("production", "preview")}})
    latest = pages.call("GET", f"/pages/projects/{project}/deployments", params={"per_page": 1, "env": "production"})[0]
    deployment = pages.call("POST", f"/pages/projects/{project}/deployments/{latest['id']}/retry")
    log("Dashboard switched to email-code sign-in; redeploying")
    for _ in range(40):
        state = pages.call("GET", f"/pages/projects/{project}/deployments/{deployment['id']}")
        stage = state.get("latest_stage", {})
        if stage.get("name") == "deploy" and stage.get("status") in ("success", "failure"):
            return stage["status"]
        if stage.get("status") == "failure":
            return "failure"
        time.sleep(10)
    return "still running"


def main(argv: list[str]) -> int:
    emails = [a.strip().lower() for a in argv if "@" in a]
    if not emails:
        print(__doc__)
        return 2
    account = os.environ.get("CF_ACCOUNT_ID", "284f1a03e12aa7416ab177db3f692c17")
    project = os.environ.get("PAGES_PROJECT", "amazon-optimization")
    access = Client(os.environ["CF_ACCESS_TOKEN"], account)
    pages = Client(os.environ.get("CF_PAGES_TOKEN") or os.environ["CF_ACCESS_TOKEN"], account)
    host = f"{project}.pages.dev"
    team_domain = ensure_organization(access, os.environ.get("ACCESS_TEAM"))
    otp_id = ensure_otp(access)
    app = ensure_app(access, host, otp_id)
    ensure_policy(access, app["id"], emails)
    result = switch_dashboard(pages, project, team_domain, app["aud"])
    print(f"Deployment: {result}. Open https://{host}/ : Cloudflare asks for your email and sends a 6-digit code.")
    return 0 if result == "success" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
