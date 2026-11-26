"""Apply the safe, mechanical fixes to WordPress and confirm each one on the live page.

What it will do, and nothing else:
  tags        add the site's tracking ID to untagged Amazon links; replace other IDs of the same account
  rel         add rel="sponsored nofollow" to Amazon links that lack it
  disclosure  add the "As an Amazon Associate" line to posts that have Amazon links and no disclosure
  blocked     point links to products listed in sites.yaml `blocked_asins` at an Amazon search
  box         add a product box near the top of pages that get Google traffic but link late

Safety: dry run unless apply=True; only the post body is edited; the previous body is saved to
backups/ and WordPress keeps it as a revision; a post is skipped if the edit would shrink it by
more than 10%; after saving, the live page is fetched again and re-audited.
"""
from __future__ import annotations

import csv
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import crawl, fixes, transform
from .config import Config
from .score import Row, page_issues
from .wp import NoAccess, WordPress

FIXES = ("tags", "rel", "disclosure", "blocked", "box")
# The audit issues each fix is expected to clear on the live page.
CLEARS = {
    "tags": {"untagged_link", "other_site_tag"},
    "rel": {"missing_rel_sponsored"},
    "disclosure": {"no_disclosure"},
    "blocked": {"blocked_product"},
    "box": {"first_link_late", "first_link_very_late"},
}


@dataclass
class Action:
    row: Row
    fixes: list[str]
    status: str = "planned"
    detail: str = ""
    post_id: int | None = None
    remaining: list[str] = field(default_factory=list)


def plan(cfg: Config, rows: list[Row], sites: list[str] | None = None) -> list[Action]:
    """Decide which fixes each audited page needs. Reads only the audit, not WordPress."""
    actions = []
    for row in rows:
        if row.page.status != 200 or (sites and row.site.domain not in sites) or not row.site.wordpress:
            continue
        if row.site.skip_fix and re.search(row.site.skip_fix, urlsplit(row.page.url).path):
            continue
        issues, wanted = set(row.issues), []
        if row.site.tags and issues & CLEARS["tags"]:
            wanted.append("tags")
        for name in ("rel", "disclosure", "blocked"):
            if issues & CLEARS[name]:
                wanted.append(name)
        if issues & CLEARS["box"] and row.score > 0 and fixes.box(row, cfg.blocked_asins):
            wanted.append("box")
        wanted = [f for f in wanted if f in cfg.auto_fix]
        if wanted:
            actions.append(Action(row=row, fixes=wanted))
    return actions


def transform_post(cfg: Config, action: Action, raw: str) -> tuple[str, Counter]:
    """Run the planned edits over a post body."""
    site, counts, html = action.row.site, Counter(), raw
    site_tag = site.tags[0] if site.tags else ""
    if "blocked" in action.fixes:
        html, counts["blocked_links_repointed"], counts["blocked_links_left_for_review"] = (
            transform.replace_blocked(html, cfg.blocked_asins, cfg.marketplace, site_tag))
    if "tags" in action.fixes and site_tag:
        html, counts["tags_fixed"] = transform.fix_tags(html, site_tag, site.tags, cfg.account_tag_prefix)
    if "rel" in action.fixes:
        html, counts["rel_added"] = transform.fix_rel(html)
    if "box" in action.fixes:
        html, counts["box_added"] = transform.insert_box(html, fixes.box(action.row, cfg.blocked_asins) or "")
    if "disclosure" in action.fixes:
        html, counts["disclosure_added"] = transform.add_disclosure(html, site.name)
    return html, +counts


def run(
    cfg: Config, rows: list[Row], out: Path, apply: bool = False, sites: list[str] | None = None,
    limit: int | None = None, backups: Path = Path("backups"), pause: float = 0.5,
    wp_factory=WordPress, verify=crawl.audit_url, log=print,
) -> list[Action]:
    actions = plan(cfg, rows, sites)[: limit or None]
    clients: dict[str, WordPress] = {}
    locked: set[str] = set()
    for action in actions:
        site, url = action.row.site, action.row.page.url
        if site.domain in locked:
            action.status = "no_access"
            continue
        wp = clients.setdefault(site.domain, wp_factory(site.domain, site.user_agent))
        try:
            post = wp.find(url)
            if post is None:
                action.status = "not_in_wordpress"
                continue
            action.post_id = post["id"]
            new, counts = transform_post(cfg, action, post["raw"])
            action.detail = ", ".join(f"{k}={v}" for k, v in counts.items())
            if new == post["raw"]:
                action.status = "nothing_to_change_in_post_body"
                continue
            if len(new) < 0.9 * len(post["raw"]):
                action.status = "aborted_would_shrink_post"
                continue
            if not apply:
                action.status = "would_change"
                continue
            backup = backups / site.domain / f"{post['id']}-{out.name}.html"
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():  # keep the oldest copy if a run is repeated
                backup.write_text(post["raw"])
            stored = wp.save(post["kind"], post["id"], new)
            if stored == post["raw"]:
                action.status = "save_had_no_effect"
                continue
        except NoAccess as exc:
            locked.add(site.domain)
            action.status, action.detail = "no_access", str(exc)
            log(f"[{site.domain}] no write access: {exc}")
            continue
        except Exception as exc:  # one bad post must not stop the run
            action.status, action.detail = "error", f"{type(exc).__name__}: {exc}"[:200]
            continue
        time.sleep(pause)
        sep = "&" if "?" in url else "?"
        live = verify(f"{url}{sep}ace_verify={int(time.time())}", site)
        targeted = set().union(*(CLEARS[f] for f in action.fixes))
        action.remaining = sorted(targeted & set(page_issues(live, site, cfg)[0])) if live.status == 200 else ["live page did not load"]
        action.status = "fixed" if not action.remaining else "saved_but_live_page_unchanged"
    write_log(out, actions)
    return actions


def write_log(out: Path, actions: list[Action]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "fix-log.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "url", "post_id", "fixes", "status", "changes", "still_failing_on_live_page"])
        for a in actions:
            w.writerow([a.row.site.domain, a.row.page.url, a.post_id or "", " ".join(a.fixes), a.status, a.detail, " ".join(a.remaining)])


def summarize(actions: list[Action]) -> str:
    table = Counter((a.row.site.domain, a.status) for a in actions)
    lines = [f"{site:36} {status:34} {n}" for (site, status), n in sorted(table.items())]
    return "\n".join(lines) or "nothing to fix"
