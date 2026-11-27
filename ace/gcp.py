"""Google service-account credentials, shared by the Search Console and Analytics pullers.

One service account reads both. Provide its JSON key in one of:
  GSC_SERVICE_ACCOUNT_JSON     the key file's contents (a GitHub Actions secret for the weekly run)
  GSC_SERVICE_ACCOUNT_FILE     a path to the key file (handy on your own computer)
Never commit the key.

Access it needs:
  Search Console  Settings > Users and permissions: add the service account's email (Full user)
                  on every property in sites.yaml. URL inspection needs Full, not Restricted.
  Analytics       Admin > Property access management: add the same email as Viewer on each
                  property listed under ga4_properties in sites.yaml.
"""
from __future__ import annotations

import json
import os
import threading

SEARCH_CONSOLE = "https://www.googleapis.com/auth/webmasters.readonly"
ANALYTICS = "https://www.googleapis.com/auth/analytics.readonly"


def service_account_info() -> dict | None:
    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        return json.loads(raw)
    path = os.environ.get("GSC_SERVICE_ACCOUNT_FILE", "").strip()
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def available() -> bool:
    return service_account_info() is not None


def session(*scopes: str):
    """An authorised requests session for the given scopes. Raises SystemExit without a key."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    info = service_account_info()
    if info is None:
        raise SystemExit("No Google service account: set GSC_SERVICE_ACCOUNT_JSON (see ace/gcp.py).")
    creds = service_account.Credentials.from_service_account_info(info, scopes=list(scopes))
    return AuthorizedSession(creds)


class PerThread:
    """One authorised session per thread: token refresh is not safe to share across threads."""

    def __init__(self, *scopes: str, factory=None):
        self.scopes, self.local = scopes, threading.local()
        self.factory = factory or (lambda: session(*scopes))

    def get(self):
        if not hasattr(self.local, "session"):
            self.local.session = self.factory()
        return self.local.session
