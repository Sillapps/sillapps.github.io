#!/usr/bin/env python3
"""Sets the <lastmod> of every hand-written URL of sitemap.xml to the date
the page last changed, so that Google can trust it and recrawl changed pages.

The date is the commit date of the last commit that touched the page file
(`git log -1 --format=%cs`), or today when the file has uncommitted changes.
The Placa Hoy city block (between the "placa-hoy:cities" markers) is left
alone: placa-hoy/build_pages.py writes it.

HOW TO RUN (from the root of the site repository, after editing a page,
before or after committing it):
    python3 tools/sitemap_lastmod.py            # every URL
    python3 tools/sitemap_lastmod.py scioperi/index.html   # only these files
    python3 tools/sitemap_lastmod.py --check    # exit 1 if a date is stale
Python 3.9+, standard library only.
"""
import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
BASE = "https://sillapps.com/"
GENERATED = re.compile(r"<!-- placa-hoy:cities:start -->.*?<!-- placa-hoy:cities:end -->", re.S)
ENTRY = re.compile(r"(<loc>([^<]+)</loc>\s*<lastmod>)([^<]+)(</lastmod>)")


def page_file(url: str) -> str:
    path = url[len(BASE):]
    return path + "index.html" if path == "" or path.endswith("/") else path


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=SITE, capture_output=True, text=True, check=True).stdout.strip()


def changed_on(path: str) -> str:
    if git("status", "--porcelain", "--", path):
        return dt.date.today().isoformat()
    return git("log", "-1", "--format=%cs", "--", path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", help="limit to these page files (paths from the site root)")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    sitemap = SITE / "sitemap.xml"
    text = sitemap.read_text(encoding="utf-8")
    generated = [m.span() for m in GENERATED.finditer(text)]
    stale = []

    def update(m: re.Match) -> str:
        if any(a <= m.start() < b for a, b in generated) or not m.group(2).startswith(BASE):
            return m.group(0)
        path = page_file(m.group(2))
        if args.files and path not in args.files:
            return m.group(0)
        if not (SITE / path).exists():
            raise SystemExit(f"sitemap.xml: {m.group(2)} has no file {path}")
        date = changed_on(path) or m.group(3)
        if date != m.group(3):
            stale.append(f"{m.group(2)}: {m.group(3)} -> {date}")
        return m.group(1) + date + m.group(4)

    new = ENTRY.sub(update, text)
    for line in stale:
        print(line)
    if args.check:
        return 1 if stale else 0
    if new != text:
        sitemap.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
