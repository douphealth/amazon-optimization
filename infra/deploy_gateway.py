"""Deploy the dashboard's email-code front door: a Cloudflare Worker behind Cloudflare Access.

Open https://<WORKER_NAME>.<account subdomain>.workers.dev, enter an allowed email address, type the
6-digit code Cloudflare emails you, and you stay signed in for 30 days. The Worker
(infra/gateway/worker.js) verifies Access's signed token itself and only then fetches the
dashboard, signing in to it with the dashboard password (a Worker secret).

    read -rs CF_API_TOKEN && export CF_API_TOKEN          # Access + Workers edit on the account
    read -rs DASHBOARD_PASSWORD && export DASHBOARD_PASSWORD
    python infra/deploy_gateway.py you@example.com         # or --owner-emails: reuse the addresses
                                                            # the account's other Access apps allow

CF_ACCOUNT_ID  default: the account with the owner's Zero Trust team
ORIGIN         default: https://amazon-optimization.pages.dev (the dashboard)
WORKER_NAME    default: commission-engine

Order, so the address never serves anything without the email code: Access application and allowed
addresses first, then the Worker (which refuses requests without a valid Access token anyway),
then the workers.dev address, then a check that Cloudflare answers it with the sign-in page.
Safe to run again.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("setup_access", HERE / "setup_access.py")
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

API = "https://api.cloudflare.com/client/v4"
COMPATIBILITY_DATE = "2025-06-01"


def owner_emails(cf) -> list[str]:
    """The addresses the account's existing Access applications allow."""
    found = set()
    for app in cf.call("GET", "/access/apps") or []:
        for policy in cf.call("GET", f"/access/apps/{app['id']}/policies") or []:
            if policy.get("decision") == "allow":
                found |= {i["email"]["email"].lower() for i in policy.get("include", []) if "email" in i}
    return sorted(found)


def upload_worker(token: str, account: str, name: str, bindings: list[dict]) -> None:
    worker = (HERE / "gateway" / "worker.js").read_text()
    check = (HERE.parent / "functions" / "_middleware.js").read_text()
    metadata = {"main_module": "worker.mjs", "compatibility_date": COMPATIBILITY_DATE, "bindings": bindings}
    resp = requests.put(
        f"{API}/accounts/{account}/workers/scripts/{name}", headers={"Authorization": f"Bearer {token}"},
        files={"metadata": (None, json.dumps(metadata), "application/json"),
               "worker.mjs": ("worker.mjs", worker, "application/javascript+module"),
               "_middleware.mjs": ("_middleware.mjs", check, "application/javascript+module")},
        timeout=120)
    body = resp.json()
    if not body.get("success"):
        raise sa.CloudflareError("upload: " + "; ".join(f"{e.get('code')}: {e.get('message')}" for e in body.get("errors", [])))


def main(argv: list[str]) -> int:
    token, password = os.environ.get("CF_API_TOKEN"), os.environ.get("DASHBOARD_PASSWORD")
    if not token or not password:
        print(__doc__)
        return 2
    account = os.environ.get("CF_ACCOUNT_ID", "5dc0401c38d9de0c6947fee40a210937")
    origin = os.environ.get("ORIGIN", "https://amazon-optimization.pages.dev")
    name = os.environ.get("WORKER_NAME", "commission-engine")
    cf = sa.Client(token, account)
    emails = owner_emails(cf) if "--owner-emails" in argv else [a.strip().lower() for a in argv if "@" in a]
    if not emails:
        print("No allowed email address: give one or more, or --owner-emails.")
        return 2
    team = sa.ensure_organization(cf, os.environ.get("ACCESS_TEAM"))
    otp = sa.ensure_otp(cf)
    host = f"{name}.{cf.call('GET', '/workers/subdomain')['subdomain']}.workers.dev"
    app = sa.ensure_app(cf, host, otp)
    sa.ensure_policy(cf, app["id"], emails)
    upload_worker(token, account, name, [
        {"type": "plain_text", "name": "ACCESS_TEAM_DOMAIN", "text": team},
        {"type": "plain_text", "name": "ACCESS_AUD", "text": app["aud"]},
        {"type": "plain_text", "name": "ORIGIN", "text": origin},
        {"type": "secret_text", "name": "DASHBOARD_PASSWORD", "text": password},
    ])
    print(f"Worker deployed: {name}")
    cf.call("POST", f"/workers/scripts/{name}/subdomain", json={"enabled": True, "previews_enabled": False})
    print(f"Address on: https://{host}/ (preview addresses off)")
    if not sa.access_enforced(host, team):
        print("Cloudflare does not answer the address with the sign-in page yet. The Worker refuses every request "
              "without a valid sign-in in the meantime. Run this again in a few minutes to confirm.")
        return 1
    print(f"Done. Open https://{host}/ : enter your email, Cloudflare sends a 6-digit code.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
