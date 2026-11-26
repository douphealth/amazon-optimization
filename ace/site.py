"""Build a static dashboard from the latest report, for hosting on Cloudflare Pages or anywhere else.

    python -m ace site --out dist

It only reads files already in the repository (reports/, docs/, data/indexnow/). It never crawls
or contacts a website, so the build is fast and cannot fail on network errors. No dependencies
beyond the standard library: the small Markdown renderer below covers what the reports use.
"""
from __future__ import annotations

import csv
import html
import json
import re
import shutil
from pathlib import Path

INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), r'<a href="\2">\1</a>'),
    (re.compile(r"(?<![\"'>=])\b(https?://[^\s<|)]+)"), r'<a href="\1">\1</a>'),
]


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    for pattern, repl in INLINE:
        text = pattern.sub(repl, text)
    return text


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown(text: str, max_rows: int | None = None) -> str:
    """Render the Markdown subset the reports use: headings, paragraphs, lists, tables, code fences."""
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        heading = re.match(r"(#{1,4})\s+(.*)", line)
        if heading:
            level = len(heading.group(1))
            slug = re.sub(r"[^a-z0-9]+", "-", heading.group(2).lower()).strip("-")
            out.append(f'<h{level} id="{slug}">{inline(heading.group(2))}</h{level}>')
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = _cells(line)
            j = i + 2
            rows = []
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_cells(lines[j]))
                j += 1
            shown = rows[:max_rows] if max_rows else rows
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in shown)
            out.append(
                '<div class="scroll"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head)
                + f"</tr></thead><tbody>{body}</tbody></table></div>"
            )
            if max_rows and len(rows) > max_rows:
                out.append(f'<p class="muted">Showing {max_rows} of {len(rows)} rows.</p>')
            i = j
            continue
        bullet = re.match(r"\s*(?:[-*]|\d+\.)\s+", line)
        if bullet:
            tag = "ol" if re.match(r"\s*\d+\.", line) else "ul"
            items = []
            while i < len(lines) and (re.match(r"\s*(?:[-*]|\d+\.)\s+", lines[i]) or (lines[i].startswith("  ") and lines[i].strip() and items)):
                if re.match(r"\s*(?:[-*]|\d+\.)\s+", lines[i]):
                    items.append(re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", lines[i]))
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        para = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,4}\s|\s*\||```|\s*(?:[-*]|\d+\.)\s+)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(out)


def sections(text: str) -> dict[str, str]:
    """Split a report into its level-2 sections, keyed by heading text."""
    parts: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            parts[current] = ""
        elif current is not None:
            parts[current] += line + "\n"
    return parts


def _find(parts: dict[str, str], start: str) -> str:
    return next((body for title, body in parts.items() if title.lower().startswith(start.lower())), "")


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="muted">Nothing recorded yet.</p>'
    body = "".join("<tr>" + "".join(f"<td>{inline(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return '<div class="scroll"><table><thead><tr>' + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + f"</tr></thead><tbody>{body}</tbody></table></div>"


CSS = """
:root{--bg:#f6f7f4;--card:#fff;--ink:#16211b;--muted:#5d6b63;--line:#dfe5df;--accent:#1f6f43;--accent-soft:#e7f3ec;--warn:#9a5b00}
@media (prefers-color-scheme:dark){:root{--bg:#101512;--card:#18201b;--ink:#e8efe9;--muted:#9aa9a0;--line:#2a352e;--accent:#6fcf97;--accent-soft:#1d2c23;--warn:#e0a84a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
header{background:var(--card);border-bottom:1px solid var(--line)}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
header .wrap{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 22px;padding-top:16px;padding-bottom:14px}
header h1{font-size:20px;margin:0}
header .date{color:var(--muted);font-size:14px}
nav{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:14px}
@media (min-width:720px){nav{margin-left:auto}}
nav a{text-decoration:none;padding:4px 0}
nav a[aria-current]{font-weight:700;border-bottom:2px solid var(--accent)}
main{padding:22px 0 60px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:0 0 26px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile b{display:block;font-size:26px;line-height:1.2;font-variant-numeric:tabular-nums}
.tile span{display:block;color:var(--muted);font-size:13px;line-height:1.35;margin-top:2px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:6px 18px 16px;margin:0 0 18px}
h2{font-size:19px;margin:16px 0 8px}
h3{font-size:16px;margin:20px 0 6px}
p,li{max-width:86ch}
.muted{color:var(--muted);font-size:14px}
.scroll{overflow-x:auto;margin:8px 0 12px;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{background:var(--accent-soft);font-weight:600;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
td a{word-break:break-word}
code{background:var(--accent-soft);padding:1px 5px;border-radius:4px;font-size:.92em}
pre{background:var(--accent-soft);padding:12px;border-radius:8px;overflow-x:auto}
pre code{background:none;padding:0}
.more{font-size:14px}
footer{color:var(--muted);font-size:13px;padding:0 0 30px}
"""

NAV = [("index.html", "Overview"), ("report.html", "Full report"), ("changes.html", "Changes made"), ("notes.html", "Notes")]


def page(title: str, date: str, current: str, body: str, depth: int = 0) -> str:
    up = "../" * depth
    here = ' aria-current="page"'
    nav = "".join(f'<a href="{up}{href}"{here if href == current else ""}>{label}</a>' for href, label in NAV)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><header><div class="wrap"><h1>Amazon Commission Engine</h1><span class="date">Report of {html.escape(date)}</span><nav>{nav}</nav></div></header>
<main><div class="wrap">{body}</div></main>
<div class="wrap"><footer>Generated from the repository's latest report. Private working data: not for search engines.</footer></div>
</body></html>"""


def latest_report(root: Path) -> Path | None:
    reports = sorted(d for d in root.iterdir() if d.is_dir() and (d / "summary.md").exists()) if root.exists() else []
    return reports[-1] if reports else None


def build(out: Path, reports: Path = Path("reports"), docs: Path = Path("docs"), state: Path = Path("data/indexnow"), mirrors: list[Path] | None = None) -> Path:
    report = latest_report(reports)
    if report is None:
        raise SystemExit(f"No report with a summary.md found under {reports}/")
    date = report.name
    summary = (report / "summary.md").read_text()
    parts = sections(summary)
    pages = _csv(report / "pages.csv")
    fixes = [r for r in _csv(report / "fix-log.csv") if r.get("status") == "fixed"]
    sent = _csv(report / "indexnow-log.csv")
    submitted = {p.stem: len(json.loads(p.read_text()).get("submitted", {})) for p in sorted(state.glob("*.json"))} if state.exists() else {}

    def total(field: str) -> int:
        return int(sum(float(r.get(field) or 0) for r in pages))

    tiles = [
        (len({r["site"] for r in pages}), "sites audited"),
        (f"{len(pages):,}", "pages crawled"),
        (f"{total('amazon_links'):,}", "Amazon links found"),
        (total("ga_amazon_clicks"), "Amazon clicks recorded by Analytics"),
        (f"{sum(submitted.values()):,}", "pages submitted to search engines"),
        (len(fixes), "pages fixed on live sites in this report"),
    ]
    tile_html = '<div class="tiles">' + "".join(f'<div class="tile"><b>{v}</b><span>{html.escape(label)}</span></div>' for v, label in tiles) + "</div>"

    portfolio = _find(parts, "Portfolio").split("###")[0]
    overview = tile_html
    overview += f"<section><h2>Portfolio</h2>{markdown(portfolio)}</section>"
    earners = _find(parts, "Pages that produce Amazon clicks")
    if earners.strip():
        overview += f'<section><h2>Pages that produce Amazon clicks</h2><p class="muted">From Google Analytics, all traffic sources.</p>{markdown(earners, max_rows=12)}<p class="more"><a href="report.html#pages-that-produce-amazon-clicks-google-analytics-all-traffic-sources">See all in the full report</a></p></section>'
    queue = _find(parts, "Work queue")
    if queue.strip():
        overview += f'<section><h2>Work queue: pages losing the most Amazon clicks</h2>{markdown(queue, max_rows=12)}<p class="more"><a href="report.html#work-queue-pages-losing-the-most-amazon-clicks">See the full queue</a></p></section>'
    changed = _find(parts, "Changes since")
    if changed.strip():
        title = next(t for t in parts if t.lower().startswith("changes since"))
        overview += f"<section><h2>{html.escape(title)}</h2>{markdown(changed)}</section>"

    change_body = "<section><h2>Fixes saved to live sites</h2>" + _table(
        ["Site", "Page", "Fix", "What changed"],
        [[r["site"], r["url"], r["fixes"], r["changes"].replace("_", " ").replace("=", ": ")] for r in fixes],
    ) + "</section>"
    change_body += "<section><h2>Pages submitted to search engines</h2><p class=\"muted\">Through IndexNow, which reaches Bing and the other engines outside Google.</p>" + _table(
        ["Site", "Pages submitted so far", "Latest run", "Engine response"],
        [[r["host"], f"{submitted.get(r['site'], 0):,}", r["status"].replace("_", " "), r["detail"]] for r in sent],
    ) + "</section>"

    notes = sorted(docs.glob("*.md")) if docs.exists() else []
    note_links = "".join(
        f'<li><a href="notes/{n.stem}.html">{html.escape(n.read_text().splitlines()[0].lstrip("# ").strip() or n.stem)}</a></li>' for n in notes
    )
    notes_body = f"<section><h2>Notes</h2><ul>{note_links or '<li>No notes yet.</li>'}</ul></section>"

    if out.exists():
        shutil.rmtree(out)
    (out / "notes").mkdir(parents=True)
    (out / "data").mkdir()
    (out / "index.html").write_text(page("Amazon Commission Engine", date, "index.html", overview))
    (out / "report.html").write_text(page(f"Full report {date}", date, "report.html", f"<section>{markdown(summary)}</section>"))
    (out / "changes.html").write_text(page("Changes made", date, "changes.html", change_body))
    (out / "notes.html").write_text(page("Notes", date, "notes.html", notes_body))
    for n in notes:
        (out / "notes" / f"{n.stem}.html").write_text(page(n.stem, date, "notes.html", f"<section>{markdown(n.read_text())}</section>", depth=1))
    for name in ("pages.csv", "links.csv", "fix-log.csv", "indexnow-log.csv"):
        if (report / name).exists():
            shutil.copy(report / name, out / "data" / name)
    # Ask search engines to stay away from this working dashboard.
    (out / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    # Hosting services differ in which folder they publish, so the same site can be written to several.
    for mirror in mirrors or []:
        if mirror.resolve() == out.resolve():
            continue
        if mirror.resolve() == Path.cwd().resolve():
            shutil.copytree(out, mirror, dirs_exist_ok=True)  # the project folder itself: add, never delete
            continue
        if mirror.exists():
            shutil.rmtree(mirror)
        shutil.copytree(out, mirror)
    return out
