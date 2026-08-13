"""Shared logic for finding translatable copy and pinning it to a unique anchor.

Both the extractor (which proposes what to translate) and the builder (which
applies it) have to agree on exactly two questions: what counts as copy, and
where a given phrase lives in the file. Keeping the answers here means they
cannot drift apart and produce a skeleton the builder then rejects.
"""

import re

# Text that must survive translation untouched: the brand, the coach's name,
# the product nouns the app itself leaves in English, map-data attribution,
# demo runner names and Turin club names, the language menu (each entry is
# deliberately written in its own language), plus bare numbers and units.
KEEP = {
    "RouteRush", "Boldi", "Mapbox", "OpenStreetMap", "routerushapp.com",
    "Instagram", "TikTok", "Torino", "Rush", "Atlas", "PRO", "PREMIUM",
    "HealthKit", "iPhone", "iOS", "App Store", "Live Activity", "Dynamic Island",
    "VS", "LIVE", "RP", "km", "km²", "m", "bpm", "/km", "3D",
    "Torino Runners", "Po River Pace", "Mole Milers", "San Salvario SC",
    "Valentino AC", "M. Kaya · km",
    "English", "Türkçe", "Italiano", "Deutsch", "Español", "Français",
}

SKIP_RE = re.compile(
    r"^(?:[\s\W\d]+"                      # pure punctuation/number
    r"|[A-Z]{2}"                          # avatar initials: MK, JD, TR…
    r"|[A-Z]\.\s?\w+"                     # demo names: M. Kaya
    r"|@\w+"                              # demo handles
    r"|\d[\d\s.,:·]*\s*(km|km²|m|bpm|/km)?\s*↑?"
    r"|Silver\s+[IVX]+"                   # tier label, same token everywhere
    r")$"
)

# Whole elements that must be translated as one unit because the sentence is
# split across markup — translating the pieces separately would force the
# translator to reproduce English word order.
ATOMIC = [
    '<h1 class="hero-h1 display" id="hero-title">Running is how<br>you take <em>ground.</em></h1>',
]


def strip_noise(src):
    body = src.split("</head>", 1)[1]
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    return re.sub(r"<!--.*?-->", "", body, flags=re.S)


def candidates(src):
    """Visible copy worth translating, in document order, deduplicated."""
    body = strip_noise(src)
    atomic_in_page = [a for a in ATOMIC if a in src]
    # Blank the atomic elements so their inner fragments are not offered
    # separately as well.
    for a in atomic_in_page:
        body = body.replace(a, "")
    out, seen = list(atomic_in_page), set(atomic_in_page)
    for raw in re.findall(r">([^<>]+)<", body):
        t = raw.strip()
        if not t or t in KEEP or SKIP_RE.match(t) or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def unique_fragment(src, text):
    """Smallest fragment containing `text` that occurs exactly once.

    Returns None when the phrase genuinely repeats — a nav label, a CTA used
    twice, the one-liner that lives in the footer, the meta description and the
    JSON-LD at once. The caller decides that every copy should change.
    """
    if src.count(text) == 1:
        return text
    wrapped = f">{text}<"
    if src.count(wrapped) == 1:
        return wrapped
    for m in re.finditer(re.escape(wrapped), src):
        start = src.rfind("<", 0, m.start())
        if start == -1:
            continue
        frag = src[start:m.end()]
        if src.count(frag) == 1:
            return frag
    return None
