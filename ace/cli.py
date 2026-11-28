"""Command line entry point: python -m ace <command>."""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import amazon, bing, changes, config, crawl, data, fixer, fixes, ga4, gcp, gsc, indexnow, products, report, score, site
from .page import Page
from .config import norm_url


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


def _load_inputs(cfg):
    """Everything scoring reads besides the crawl: Search Console, Bing, Analytics, Google's index
    verdicts, Bing crawl errors and Associates reports."""
    gsc_by_site, gsc_meta = {}, {}
    for s in cfg.sites:
        rows, meta = data.load_gsc(s.domain)
        if rows or meta:  # an empty export still means "Google showed nothing"
            gsc_by_site[s.domain], gsc_meta[s.domain] = rows, meta
    return {
        "gsc_by_site": gsc_by_site, "gsc_meta": gsc_meta, "tag_stats": data.load_associates(),
        "ga": {s.domain: data.load_ga4(s.domain) for s in cfg.sites},
        "bing": {s.domain: data.load_bing(s.domain)[0] for s in cfg.sites},
        "index": {s.domain: gsc.load_index(s.domain) for s in cfg.sites},
        "bing_errors": {s.domain: bing.load_crawl_errors(s.domain) for s in cfg.sites},
    }


def _score(cfg, pages_by_site, inputs):
    return score.build_rows(cfg, pages_by_site, inputs["gsc_by_site"], inputs["tag_stats"], inputs["ga"],
                            bing_by_site=inputs["bing"], index_by_site=inputs["index"], bing_errors_by_site=inputs["bing_errors"])


def _scored(cfg, args):
    pages_by_site, _ = report.load_audit(args.out)
    return _score(cfg, pages_by_site, _load_inputs(cfg))


def _picker(cfg):
    """Real-product boxes need Creators API credentials; without them boxes reuse page links only."""
    client = amazon.Creators.from_env(marketplace=cfg.marketplace)
    if client is None:
        print("Creators API credentials not set (AMAZON_CREATORS_CREDENTIAL_ID/SECRET): product boxes reuse the page's own links only")
        return None
    picker = products.Picker(client, products.load_plan(), blocked=set(cfg.blocked_asins))
    registry = products.load_registry()
    picker.known = set(registry)
    picker.left_out = {u for u, r in registry.items() if r.get("removed_by_editor")}
    picker.registered = picker.known - picker.left_out
    return picker


def _fail_if_mostly_errors(actions, what: str) -> None:
    """An unattended run that failed on most pages must show as failed, not as a quiet success."""
    tried = [a for a in actions if a.status not in ("left_for_next_run_time_budget",)]
    errors = [a for a in tried if a.status == "error" or "amazon_unavailable" in a.detail]
    if tried and len(errors) > len(tried) / 2:
        raise SystemExit(f"{what}: {len(errors)} of {len(tried)} pages failed (first: {errors[0].detail[:200]})")


def cmd_fix(cfg, args) -> None:
    picker = _picker(cfg)
    if picker and args.rebuild_boxes:
        picker.known = set()  # re-render registered boxes too (e.g. after a design change)
    actions = fixer.run(cfg, _scored(cfg, args), args.out, apply=args.apply, sites=args.site, limit=args.limit,
                        require_login=args.only_with_login, picker=picker,
                        registry=products.REGISTRY if picker else None, max_minutes=args.max_minutes, pause=args.pause)
    if picker:
        print(f"Creators API calls: {picker.client.calls}")
    print(fixer.summarize(actions))
    _fail_if_mostly_errors(actions, "fix")
    print(f"log: {args.out}/fix-log.csv" + ("" if args.apply else "  (dry run: nothing was changed; add --apply)"))


def cmd_refresh_boxes(cfg, args) -> None:
    """Keep live product boxes current: a box whose product went out of stock, lost its image or
    changed its name or image is rebuilt (same rules as when it was placed). Others are left alone."""
    picker = _picker(cfg)
    if picker is None:
        raise SystemExit("refresh-boxes needs Creators API credentials")
    registry = products.load_registry()
    live_boxes = {u: r for u, r in registry.items() if not r.get("removed_by_editor")}
    tag_of = lambda rec: (cfg.site(rec["site"]).tags or [cfg.default_tag])[0]
    by_tag: dict[str, set[str]] = {}
    for rec in live_boxes.values():  # ten ASINs per call across all pages, then per page from the cache
        by_tag.setdefault(tag_of(rec), set()).update(rec["asins"])
    unknown = 0
    for tag, asins in by_tag.items():
        try:
            picker.client.get_items(sorted(asins), tag)
        except amazon.AmazonError as exc:
            print(f"getItems for {tag}: {exc}")
    stale = []
    for url, rec in live_boxes.items():
        if args.site and rec["site"] not in args.site:
            continue
        try:
            live = picker.client.get_items(rec["asins"], tag_of(rec))
        except amazon.AmazonError as exc:  # unknown is not gone: leave the box, try again tomorrow
            unknown += 1
            print(f"{url}: could not check ({exc})")
            continue
        reasons = []
        for i, asin in enumerate(rec["asins"]):
            it = live.get(asin)
            if asin in picker.blocked:
                reasons.append(f"{asin} blocked")
            elif not it or not it.available or not it.image:
                reasons.append(f"{asin} gone")
            elif not picker.image_ok(it.image):
                reasons.append(f"{asin} image broken")
            elif (rec.get("image_fp") or [""] * 9)[i] not in ("", products.fingerprint(it.image)) or \
                    (rec.get("name_fp") or [""] * 9)[i] not in ("", products.fingerprint(products.display_name(it))):
                reasons.append(f"{asin} changed")
        if reasons:
            print(f"{url}: {', '.join(reasons)}")
            site = cfg.site(rec["site"])
            stale.append(score.Row(site=site, page=Page(url=url, status=200, has_box=True, h1=rec.get("title", "")), gsc=None))
    print(f"{len(live_boxes)} boxes checked, {len(stale)} to rebuild, {unknown} could not be checked, {picker.client.calls} Creators API calls")
    if stale:
        picker.known -= {r.page.url for r in stale}  # these are exactly the boxes to rebuild
        actions = fixer.run(cfg, stale, args.out, apply=args.apply, require_login=args.only_with_login,
                            picker=picker, registry=products.REGISTRY, max_minutes=args.max_minutes)
        print(fixer.summarize(actions))
        _fail_if_mostly_errors(actions, "refresh-boxes")
    if live_boxes and unknown > len(live_boxes) / 2:
        raise SystemExit(f"refresh-boxes: {unknown} of {len(live_boxes)} boxes could not be checked")


def cmd_submit(cfg, args) -> None:
    batches = indexnow.run(_scored(cfg, args), args.out, apply=args.apply, sites=args.site)
    print(indexnow.summarize(batches))
    print(f"log: {args.out}/indexnow-log.csv" + ("" if args.apply else "  (dry run: nothing was sent; add --apply)"))


def cmd_site(cfg, args) -> None:
    out = site.build(args.site_out, cfg=cfg, mirrors=[Path(m) for m in args.mirror or []])
    print(f"dashboard written to {out}/index.html")


def cmd_rank(cfg, args) -> None:
    pages_by_site, sitemaps = report.load_audit(args.out)
    inputs = _load_inputs(cfg)
    gsc_meta, tag_stats = inputs["gsc_meta"], inputs["tag_stats"]
    rows = _score(cfg, pages_by_site, inputs)
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


def _inspection_targets(cfg, args) -> list:
    """URLs to inspect per site, most valuable first: pages with search or analytics demand, then
    pages with Amazon links, then the rest. Taken from the audit in --out (or the latest one),
    else straight from the sitemaps."""
    audits = sorted(Path("reports").glob("*/audit.json"))
    source = args.out / "audit.json" if (args.out / "audit.json").exists() else (audits[-1] if audits else None)
    pages_by_site = report.load_audit(source.parent)[0] if source else {}
    targets = []
    for s in _sites(cfg, args.site):
        pages = pages_by_site.get(s.domain)
        if pages is None:
            urls = list(crawl.discover(s))
            linked = set()
        else:
            ok = [p for p in pages if p.status == 200 and not p.noindex]
            urls = [p.url for p in ok]
            linked = {p.url for p in ok if p.content_links}
        demand = {**bing.load_pages(s.domain), **data.load_gsc(s.domain)[0], **data.load_ga4(s.domain)}
        def weight(url):
            d = demand.get(norm_url(url))
            return (0 if d else 1, 0 if url in linked else 1)
        targets.append((s, sorted(urls, key=weight)))
    return targets


def cmd_pull(cfg, args) -> None:
    """Pull every data source this run has credentials for: Search Console (pages, queries, daily,
    URL inspection), Bing Webmaster and Google Analytics. Sources without credentials are skipped."""
    sites = _sites(cfg, args.site)
    wanted = set((args.sources or "gsc,bing,ga4,inspect").split(","))
    requested = set(wanted)
    if wanted & {"gsc", "inspect", "ga4"} and not gcp.available():
        print("No Google service account (GSC_SERVICE_ACCOUNT_JSON): skipping Search Console and Analytics")
        wanted -= {"gsc", "inspect", "ga4"}
    if "bing" in wanted and not bing.available():
        print("No BING_API_KEY: skipping Bing")
        wanted.discard("bing")
    problems: dict[str, list[str]] = {}

    def logger(key):
        def log(message):
            print(message)
            if " failed" in message or "could not" in message:
                problems.setdefault(key, []).append(message)
        return log

    steps = [("gsc", "Search Console", lambda log: gsc.pull(sites, days=args.days, log=log)),
             ("bing", "Bing", lambda log: bing.pull(sites, log=log)),
             ("ga4", "Analytics", lambda log: ga4.pull(sites, days=args.days, log=log)),
             ("inspect", "URL inspection", lambda log: gsc.inspect(_inspection_targets(cfg, args), log=log))]
    path = Path("data") / "pull-status.json"
    try:  # sources not requested this time keep their last status
        status = json.loads(path.read_text()).get("sources", {}) if path.exists() else {}
    except ValueError:
        status = {}
    for key, name, run in steps:
        if key not in requested:
            continue
        if key not in wanted:
            status[key] = "skipped: no credentials"
            continue
        try:
            run(logger(key))
        except Exception as exc:  # one source failing must not cost the others, or the report
            print(f"{name} pull failed: {exc}")
            problems.setdefault(key, []).append(f"{name} pull failed: {exc}")
        status[key] = "ok" if key not in problems else f"problems: {'; '.join(problems[key])[:400]}"
    Path("data").mkdir(exist_ok=True)
    path.write_text(json.dumps({"pulled": date.today().isoformat(), "sources": status}, indent=1))
    if problems:  # the workflow carries on (continue-on-error) but the run records the failure
        raise SystemExit(f"pull finished with problems in: {', '.join(problems)}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="ace", description=__doc__)
    parser.add_argument("--config", default="sites.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn, help_text in [
        ("audit", cmd_audit, "crawl every site and save the raw audit"),
        ("rank", cmd_rank, "score a saved audit and write summary, CSVs and fix drafts"),
        ("run", cmd_run, "audit + rank"),
        ("pull", cmd_pull, "download Search Console, URL inspection, Bing and Analytics data (whatever has credentials)"),
        ("gsc-pull", cmd_gsc_pull, "download Search Console data only (needs a service account)"),
        ("fix", cmd_fix, "apply the safe fixes to WordPress (dry run unless --apply)"),
        ("refresh-boxes", cmd_refresh_boxes, "rebuild product boxes whose products went out of stock or changed (dry run unless --apply)"),
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
        p.add_argument("--pause", type=float, default=0.5, help="fix: seconds to wait after each save (raise it for a slow site)")
        p.add_argument("--max-minutes", type=float, help="fix/refresh-boxes: stop taking new pages after this long, so the run can still commit")
        p.add_argument("--rebuild-boxes", action="store_true", help="fix: also rebuild product boxes that are already live")
        p.add_argument("--sources", help="pull: comma-separated subset of gsc,bing,ga4,inspect (default: all)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # progress shows up live in CI logs
    args.fn(config.load(args.config), args)


if __name__ == "__main__":
    main()
