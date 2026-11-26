"""Command line entry point: python -m ace <command>."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import changes, config, crawl, data, fixer, fixes, gsc, indexnow, report, score, site


def _sites(cfg, only):
    return [s for s in cfg.sites if not only or s.domain in only]


def cmd_audit(cfg, args) -> None:
    sites = _sites(cfg, args.site)
    def one(site):  # also crawl pages analytics shows visitors on, even if no sitemap lists them
        return crawl.crawl(site, extra_urls=[v["url"] for v in data.load_ga4(site.domain).values()])

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(one, sites))
    pages_by_site = {s.domain: pages for s, (pages, _) in zip(sites, results)}
    sitemaps = {s.domain: sm for s, (_, sm) in zip(sites, results)}
    share = crawl.loaded_share(pages_by_site)
    if share < 0.5:  # blocked crawl (e.g. a firewall challenge): never overwrite a good report with it
        raise SystemExit(f"Only {share:.0%} of pages loaded. The crawl looks blocked; nothing was saved.")
    report.save_audit(args.out, pages_by_site, sitemaps)
    print(f"audit saved to {args.out}/audit.json")


def _scored(cfg, args):
    pages_by_site, sitemaps = report.load_audit(args.out)
    gsc_by_site = {s.domain: data.load_gsc(s.domain)[0] for s in cfg.sites}
    ga = {s.domain: data.load_ga4(s.domain) for s in cfg.sites}
    return score.build_rows(cfg, pages_by_site, gsc_by_site, data.load_associates(), ga)


def cmd_fix(cfg, args) -> None:
    actions = fixer.run(cfg, _scored(cfg, args), args.out, apply=args.apply, sites=args.site, limit=args.limit,
                        require_login=args.only_with_login)
    print(fixer.summarize(actions))
    print(f"log: {args.out}/fix-log.csv" + ("" if args.apply else "  (dry run: nothing was changed; add --apply)"))


def cmd_submit(cfg, args) -> None:
    batches = indexnow.run(_scored(cfg, args), args.out, apply=args.apply, sites=args.site)
    print(indexnow.summarize(batches))
    print(f"log: {args.out}/indexnow-log.csv" + ("" if args.apply else "  (dry run: nothing was sent; add --apply)"))


def cmd_site(cfg, args) -> None:
    out = site.build(args.site_out, cfg=cfg, mirrors=[Path(m) for m in args.mirror or []])
    print(f"dashboard written to {out}/index.html")


def cmd_rank(cfg, args) -> None:
    pages_by_site, sitemaps = report.load_audit(args.out)
    gsc_by_site, gsc_meta = {}, {}
    for site in cfg.sites:
        rows, meta = data.load_gsc(site.domain)
        if rows or meta:  # an empty export still means "Google showed nothing"
            gsc_by_site[site.domain], gsc_meta[site.domain] = rows, meta
    tag_stats = data.load_associates()
    ga = {s.domain: data.load_ga4(s.domain) for s in cfg.sites}
    rows = score.build_rows(cfg, pages_by_site, gsc_by_site, tag_stats, ga)
    report.write_csvs(args.out, rows)
    report.write_summary(args.out, cfg, rows, sitemaps, gsc_meta, tag_stats, previous=changes.previous_report(args.out))
    written = fixes.write_fixes(rows, args.out / "fixes", top=args.fixes, blocked=cfg.blocked_asins)
    print(f"summary: {args.out}/summary.md | {len(written)} fix drafts in {args.out}/fixes/")


def cmd_run(cfg, args) -> None:
    data.ensure_folders([s.domain for s in cfg.sites])
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
        ("fix", cmd_fix, "apply the safe fixes to WordPress (dry run unless --apply)"),
        ("submit", cmd_submit, "send new and changed pages to search engines via IndexNow (dry run unless --apply)"),
        ("site", cmd_site, "build the static dashboard from the latest report"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(fn=fn)
        p.add_argument("--out", type=Path, default=Path("reports") / date.today().isoformat())
        p.add_argument("--site", action="append", help="limit to this domain (repeatable)")
        p.add_argument("--fixes", type=int, default=25, help="how many fix drafts to write")
        p.add_argument("--days", type=int, default=28, help="Search Console window")
        p.add_argument("--apply", action="store_true", help="fix/submit: really save changes or send URLs")
        p.add_argument("--limit", type=int, help="fix: stop after this many pages")
        p.add_argument("--site-out", type=Path, default=Path("dist"), help="site: folder to write the dashboard to")
        p.add_argument("--mirror", nargs="*", help="site: extra folders to receive a copy of the dashboard")
        p.add_argument("--only-with-login", action="store_true", help="fix: skip sites that have no WP_AUTH_<DOMAIN> variable")
    args = parser.parse_args(argv)
    args.fn(config.load(args.config), args)


if __name__ == "__main__":
    main()
