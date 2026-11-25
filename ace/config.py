"""Load sites.yaml into plain dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml


@dataclass
class Site:
    domain: str
    name: str
    gsc_property: str = ""
    tags: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    user_agent: str = "Mozilla/5.0"
    max_urls: int = 1500
    concurrency: int = 4
    skip_sitemaps: str = ""


@dataclass
class Config:
    account_tag_prefix: str
    marketplace: str
    sites: list[Site]

    def site(self, domain: str) -> Site:
        for s in self.sites:
            if s.domain == domain:
                return s
        raise KeyError(f"{domain} is not in sites.yaml")


def load(path: str | Path = "sites.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    defaults = raw.get("defaults", {})
    sites = []
    for entry in raw["sites"]:
        merged = {**defaults, **entry}
        merged.setdefault("name", entry["domain"])
        sites.append(Site(**merged))
    return Config(
        account_tag_prefix=raw.get("account_tag_prefix", ""),
        marketplace=raw.get("marketplace", "www.amazon.com"),
        sites=sites,
    )


def norm_url(url: str) -> str:
    """Join key for a page: host without www, path without trailing slash, no query or fragment."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}"
