"""Minimal WordPress REST client: find a post by its public URL, read its raw content, save it.

Authentication is a WordPress Application Password (Users > Profile > Application Passwords).
Provide it as the environment variable WP_AUTH_<DOMAIN>, e.g.

    WP_AUTH_PLANTASTICHAVEN_COM="username:abcd efgh ijkl mnop qrst uvwx"

Never put it in sites.yaml or commit it. When the variable is absent the client sends no
credentials, which works where a network proxy adds them and fails cleanly elsewhere.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

import requests

from .config import norm_url


class NoAccess(Exception):
    """The site refused to show or save raw post content (missing or wrong credentials)."""


def auth_for(domain: str) -> tuple[str, str] | None:
    raw = os.environ.get("WP_AUTH_" + re.sub(r"[^A-Za-z0-9]", "_", domain).upper(), "")
    user, sep, password = raw.partition(":")
    return (user, password) if sep and user and password else None


class WordPress:
    def __init__(self, domain: str, user_agent: str, session: requests.Session | None = None):
        self.base = f"https://{domain}/wp-json/wp/v2"
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        if session is None:
            self.session.auth = auth_for(domain)

    def _check(self, resp: requests.Response) -> requests.Response:
        if resp.status_code in (401, 403):
            raise NoAccess(f"{resp.status_code} from {resp.url.split('?')[0]}")
        resp.raise_for_status()
        return resp

    def find(self, url: str) -> dict | None:
        """Return {kind, id, link, modified, raw} for the post or page published at `url`."""
        slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        if not slug:
            return None
        for kind in ("posts", "pages"):
            resp = self._check(self.session.get(
                f"{self.base}/{kind}",
                params={"slug": slug, "context": "edit", "_fields": "id,link,modified,content,status"},
                timeout=40,
            ))
            for item in resp.json():
                if norm_url(item["link"]) == norm_url(url) and item.get("status") == "publish":
                    return {
                        "kind": kind, "id": item["id"], "link": item["link"],
                        "modified": item["modified"], "raw": item["content"]["raw"],
                    }
        return None

    def save(self, kind: str, post_id: int, content: str) -> str:
        """Save new content (WordPress keeps the old version as a revision). Returns what was stored."""
        resp = self._check(self.session.post(
            f"{self.base}/{kind}/{post_id}",
            params={"context": "edit", "_fields": "id,content"},
            json={"content": content}, timeout=60,
        ))
        return resp.json()["content"]["raw"]
