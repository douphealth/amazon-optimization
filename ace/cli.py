"""Command line entry point: python -m ace <command>."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import changes, config, crawl, data, fixes, gsc, report, score


def _sites(cfg, only):
    return [s for s in cfg.sites if not only or s.domain in only]


def cmd_audit(cfg, args) -> None:
    sites = _sites(cfg, args.site)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(crawl.crawl, sites))
    pages_by_site = {s.domain: pages for s, (pages, _) in zip(sites, results)}
    sitemaps = {s.domain: sm for s, (_, sm) in zip(sites, results)}
    report.save_audit(args.out, pages_by_site, sitemaps)
    print(f"audit saved to {args.out}/audit.json")


def cmd_rank(cfg, args) -> None:
    pages_by_site, sitemaps = report.load_audit(args.out)
    gsc_by_site, gsc_meta = {}, {}
    for site in cfg.sites:
        rows, meta = data.load_gsc(site.domain)
        if rows or meta:  # an empty export still means "Google showed nothing"
            gsc_by_site[site.domain], gsc_meta[site.domain] = rows, meta
    tag_stats = data.load_associates()
    rows = score.build_rows(cfg, pages_by_site, gsc_by_site, tag_stats)
    report.write_csvs(args.out, rows)
    report.write_summary(args.out, cfg, rows, sitemaps, gsc_meta, tag_stats, previous=changes.previous_report(args.out))
    written = fixes.write_fixes(rows, args.out / "fixes", top=args.fixes, blocked=cfg.blocked_asins)
    print(f"summary: {args.out}/summary.md | {len(written)} fix drafts in {args.out}/fixes/")


def cmd_run(cfg, args) -> None:
    cmd_audit(cfg, args)
    cmd_rank(cfg, args)


def cmd_gsc_pull(cfg, args) -> None:
    gsc.pull(_sites(cfg, args.site), days=args.days)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="ace", description=__doc__)
    parser.add_argument("--config", default="sites.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn, help_text in [
        ("audit", cmd_audit, "crawl every site and save the raw audit"),
        ("rank", cmd_rank, "score a saved audit and write summary, CSVs and fix drafts"),
        ("run", cmd_run, "audit + rank"),
        ("gsc-pull", cmd_gsc_pull, "download Search Console page data (needs a service account)"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(fn=fn)
        p.add_argument("--out", type=Path, default=Path("reports") / date.today().isoformat())
        p.add_argument("--site", action="append", help="limit to this domain (repeatable)")
        p.add_argument("--fixes", type=int, default=25, help="how many fix drafts to write")
        p.add_argument("--days", type=int, default=28, help="Search Console window")
    args = parser.parse_args(argv)
    args.fn(config.load(args.config), args)


if __name__ == "__main__":
    main()
