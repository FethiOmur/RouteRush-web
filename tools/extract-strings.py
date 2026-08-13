#!/usr/bin/env python3
"""Emit a translation skeleton of unique HTML fragments for one page.

The build replaces phrases by exact match, so every key has to occur exactly
once in the source. Plain words like "Territory", "Time" or "Distance" appear
several times, so this widens each one to the smallest surrounding fragment
that IS unique — usually `>Territory</a>` or the whole element — and reports
anything it still cannot disambiguate.

Usage:  python3 tools/extract-strings.py index.html > /tmp/skeleton.json
"""

import html as htmlmod
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Text that must survive translation untouched: the brand, the coach's name,
# the product nouns the app itself leaves in English, map-data attribution,
# demo runner names and club names (Turin is Turin in every language), plus
# bare numbers and units.
KEEP = {
    "RouteRush", "Boldi", "Mapbox", "OpenStreetMap", "routerushapp.com",
    "Instagram", "TikTok", "Torino", "Rush", "Atlas", "PRO", "PREMIUM",
    "HealthKit", "iPhone", "iOS", "App Store", "Live Activity", "Dynamic Island",
    "VS", "LIVE", "RP", "km", "km²", "m", "bpm", "/km", "3D",
}
SKIP_RE = re.compile(
    r"^(?:[\s\W\d]+"                      # pure punctuation/number
    r"|[A-Z]{2}"                          # avatar initials: MK, JD, TR…
    r"|[A-Z]\.\s?\w+"                     # demo names: M. Kaya
    r"|@\w+"                              # demo handles
    r"|\d[\d\s.,:·]*\s*(km|km²|m|bpm|members|/km)?\s*↑?"
    r"|Silver\s+[IVX]+"                   # tier label, same token everywhere
    r")$"
)


def candidates(src):
    body = src.split("</head>", 1)[1]
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    out, seen = [], set()
    for raw in re.findall(r">([^<>]+)<", body):
        t = raw.strip()
        if not t or t in KEEP or SKIP_RE.match(t) or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def unique_fragment(src, text):
    """Smallest fragment containing `text` that occurs exactly once."""
    if src.count(text) == 1:
        return text
    wrapped = f">{text}<"
    if src.count(wrapped) == 1:
        return wrapped
    # Widen leftwards to the opening tag, e.g. `<a href="#coach">Coach<`.
    for m in re.finditer(re.escape(wrapped), src):
        start = src.rfind("<", 0, m.start())
        if start == -1:
            continue
        frag = src[start:m.end()]
        if src.count(frag) == 1:
            return frag
    return None


def main():
    page = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    src = (ROOT / page).read_text()
    skeleton, repeated = {}, []
    for t in candidates(src):
        frag = unique_fragment(src, t)
        if frag is None:
            # Genuinely repeated copy — a nav label, a CTA used twice, the
            # one-liner in footer + meta + JSON-LD. Emit it with the `*`
            # marker so the build changes every copy.
            repeated.append(t)
            skeleton["*" + t] = htmlmod.unescape(t)
            continue
        skeleton[frag] = htmlmod.unescape(t)
    if repeated:
        print(f"// {len(repeated)} phrase(s) repeat and were marked `*` "
              f"(every occurrence gets the same translation):", file=sys.stderr)
        for t in repeated:
            print(f"//   {t[:70]!r} x{src.count(t)}", file=sys.stderr)
    print(json.dumps({page: skeleton}, ensure_ascii=False, indent=2))
    print(f"// {len(skeleton)} translatable fragments in {page}", file=sys.stderr)


if __name__ == "__main__":
    main()
