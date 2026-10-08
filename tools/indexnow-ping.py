#!/usr/bin/env python3
"""Submit changed pages to IndexNow (Bing, Yandex, Naver, Seznam).

Run by .github/workflows/pages.yml after a successful deploy. Pass changed repo
paths as arguments (or --all); only paths that map to a URL in sitemap.xml are
submitted, so assets and tooling changes never trigger a ping.

    python3 tools/indexnow-ping.py --dry-run index.html tr/faq.html
    python3 tools/indexnow-ping.py --all
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

HOST = "routerushapp.com"
KEY = "68fb31e63eb7e7d507ed6124e3a76b92"
ENDPOINT = "https://api.indexnow.org/indexnow"
ROOT = pathlib.Path(__file__).resolve().parent.parent


def sitemap_urls() -> list[str]:
    xml = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def path_to_url(path: str) -> str:
    path = path.removeprefix("./")
    if path == "index.html":
        return f"https://{HOST}/"
    if path.endswith("/index.html"):
        return f"https://{HOST}/{path[: -len('index.html')]}"
    return f"https://{HOST}/{path}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="changed repo-relative paths")
    ap.add_argument("--all", action="store_true", help="submit every sitemap URL")
    ap.add_argument("--dry-run", action="store_true", help="print the payload, send nothing")
    args = ap.parse_args()

    known = sitemap_urls()
    if args.all:
        urls = known
    else:
        wanted = {path_to_url(p) for p in args.paths}
        urls = [u for u in known if u in wanted]

    if not urls:
        print("indexnow: no sitemap pages changed, nothing to submit")
        return 0

    payload = {
        "host": HOST,
        "key": KEY,
        "keyLocation": f"https://{HOST}/{KEY}.txt",
        "urlList": urls,
    }
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    print(f"indexnow: HTTP {status} for {len(urls)} URL(s)")
    for u in urls:
        print(f"  {u}")
    # 200 = accepted, 202 = accepted, key validation pending
    return 0 if status in (200, 202) else 1


if __name__ == "__main__":
    sys.exit(main())
