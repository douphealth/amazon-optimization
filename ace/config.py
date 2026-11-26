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
    wordpress: bool = True   # False: the fixer leaves this site alone
    skip_fix: str = ""      # regex of URL paths the fixer must not touch (non-WordPress sections)


@dataclass
class Config:
    account_tag_prefix: str
    marketplace: str
    sites: list[Site]
    # {ASIN: search phrase to link instead, or None to reuse the link's own text}
    blocked_asins: dict[str, str | None] = field(default_factory=dict)
    auto_fix: list[str] = field(default_factory=list)

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
        blocked_asins=_blocked(raw.get("blocked_asins")),
        auto_fix=list(raw.get("auto_fix") or []),
    )


def _blocked(value) -> dict[str, str | None]:
    """Accept either a list of ASINs or a mapping of ASIN to replacement search phrase."""
    if isinstance(value, dict):
        return {str(k): (str(v) if v else None) for k, v in value.items()}
    return {str(k): None for k in (value or [])}


def norm_url(url: str) -> str:
    """Join key for a page: host without www, path without trailing slash, no query or fragment."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}"
