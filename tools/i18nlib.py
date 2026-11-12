"""Shared logic for finding translatable copy.

The builder (which applies translations) and the extractor (which proposes
what to translate) have to agree on three questions: where in a page copy can
live, what counts as copy, and what a translation key looks like. Keeping the
answers here means they cannot drift apart and produce a skeleton the builder
then rejects.

A key is the English text exactly as it is written in the source: the stripped
text of one text node, the whole value of one attribute or JSON-LD content
field, or (when it starts with `<`) one whole element whose sentence is split
across markup. The builder matches text-node keys as substrings and attribute
and JSON-LD keys as whole values.
"""

import html as htmlmod
import json
import re

# Regions that are code, not copy. A naive whole-file replace turns
# `setTimeout` into `setSüreout` and `TerritoryRenderer` into `BölgeRenderer`,
# because "Time" and "Territory" are both legitimate copy elsewhere on the
# page. That shipped once in development and killed the map outright, so
# replacement is confined to text nodes, a whitelist of human-readable
# attributes, and the JSON-LD block.
SEGMENT_RE = re.compile(
    r'(<script\b(?![^>]*application/ld\+json)[^>]*>.*?</script>'   # JS
    r'|<style\b[^>]*>.*?</style>'                                  # CSS
    r'|<!--.*?-->'                                                 # comments
    r'|<script\b[^>]*application/ld\+json[^>]*>.*?</script>'       # JSON-LD
    r'|<[^>]+>)',                                                  # any tag
    re.S)

# Attribute values a reader actually sees or hears.
ATTR_RE = re.compile(
    r'\b(alt|title|aria-label|placeholder|content)="([^"]*)"')

# The only JSON-LD fields that hold copy. Everything else in that block is
# structure — vocabulary schema.org defines, not language a visitor reads.
# Treating the whole block as prose shipped `"@type": "FAQPage"` to Turkish as
# `"SSSPage"`, because "FAQ" is a key there and "SSS" is its translation. There
# is no such type, so Google saw no FAQ markup on the Turkish page at all. It
# was live from the six-locale launch until it was found; nothing looked wrong,
# because the visible copy was perfect and the rich result simply never
# appeared. Audited when this narrowed: across both pages and five locales,
# every legitimate JSON-LD translation was already a whole-value match of one
# of these three fields (1 in index.html, 20 in faq.html), and the only
# substring match in the entire corpus was the corruption above.
LD_CONTENT_FIELDS = ("description", "name", "text", "headline")
LD_FIELD_RE = re.compile(
    r'"(' + "|".join(LD_CONTENT_FIELDS) + r')":\s*"((?:[^"\\]|\\.)*)"')

# `content` is also used for plain configuration (`viewport`, `theme-color`,
# `twitter:card`). Only these meta fields carry copy; the builder requires each
# of them to be translated explicitly (see require_head_copy there).
HEAD_META = ("description", "og:title", "og:description", "og:image:alt",
             "twitter:title", "twitter:description")
HEAD_META_RE = re.compile(
    r'<meta\s+(?:name|property)="(?:' + "|".join(map(re.escape, HEAD_META)) + r')"')

# Text that must survive translation untouched: the brand, the coach's name,
# the product nouns the app itself leaves in English, map-data attribution,
# demo runner names and Turin club names, the language menu (each entry is
# deliberately written in its own language), plus bare numbers and units.
KEEP = {
    "RouteRush", "Boldi", "Mapbox", "OpenStreetMap", "routerushapp.com",
    "Instagram", "TikTok", "Torino", "Rush", "Atlas", "PRO", "PREMIUM",
    "HealthKit", "iPhone", "iOS", "App Store", "Live Activity", "Dynamic Island",
    "VS", "LIVE", "RP", "km", "km²", "m", "bpm", "/km", "3D",
    "&times;",                       # the language hint's dismiss glyph
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


def segments(src):
    """Yield (text, kind) pairs covering the whole document.

    kind is True for a text node, "attrs" for a tag, "ldjson" for a JSON-LD
    block and False for code or comments, which are never touched.
    """
    pos = 0
    for m in SEGMENT_RE.finditer(src):
        if m.start() > pos:
            yield src[pos:m.start()], True          # text node
        seg = m.group(0)
        low = seg[:200].lower()
        if low.startswith("<!--") or low.startswith("<script") and "ld+json" not in low \
                or low.startswith("<style"):
            yield seg, False                        # code or comment: untouched
        elif low.startswith("<script"):
            yield seg, "ldjson"                     # JSON-LD: copy fields only
        else:
            yield seg, "attrs"                      # a tag: whitelisted attrs only
        pos = m.end()
    if pos < len(src):
        yield src[pos:], True


def scope(src):
    """(prose, whole-value slots) — the two ways a translation can land.

    They are kept apart because they match by different rules: prose by
    substring, an attribute or a JSON-LD content field only as a whole value.
    Flattening them into one blob is what let a key that exists solely inside a
    longer attribute look present while never actually being applied.
    """
    prose, exact = [], []
    for seg, kind in segments(src):
        if kind is True:
            prose.append(seg)
        elif kind == "attrs":
            exact.extend(m.group(2) for m in ATTR_RE.finditer(seg))
        elif kind == "ldjson":
            exact.extend(m.group(2) for m in LD_FIELD_RE.finditer(seg))
    return "\n".join(prose), exact


def is_copy(text):
    """True when `text` is human-readable English that a translator must see.

    False for the allow-list (brand, product nouns, demo data), bare numbers
    and punctuation, and anything with no word in it — entities such as
    `&amp;` and `&times;` decode to symbols and so drop out here.
    """
    t = htmlmod.unescape(" ".join(text.split()))
    if not t or t in KEEP or text.strip() in KEEP or SKIP_RE.match(t):
        return False
    return re.search(r"[^\W\d_]{2,}", t) is not None


def blank(src, elements):
    """`src` with each whole element removed, so its pieces are not offered
    (or checked) a second time on their own."""
    for el in elements:
        src = src.replace(el, "")
    return src


def units(src):
    """Yield (kind, raw) for every piece of copy a translation can target.

    kind is "text" (the whole text node, untrimmed), "attr" or "ld" (the whole
    value). Attributes that are configuration rather than copy are skipped.
    """
    for seg, kind in segments(src):
        if kind is True:
            yield "text", seg
        elif kind == "attrs":
            for m in ATTR_RE.finditer(seg):
                if m.group(1) == "content" and not HEAD_META_RE.match(seg):
                    continue
                yield "attr", m.group(2)
        elif kind == "ldjson":
            for m in LD_FIELD_RE.finditer(seg):
                yield "ld", m.group(2)


def ld_decode(raw):
    """The text a JSON-LD string value holds (undo its JSON escaping)."""
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return raw


def candidates(src):
    """(kind, key) for each distinct piece of copy worth translating, in
    document order. kind is "element", "text", "attr" or "ld"; key is the
    English exactly as the builder looks it up."""
    atomic = [a for a in ATOMIC if a in src]
    out, seen = [("element", a) for a in atomic], set(atomic)
    for kind, raw in units(blank(src, atomic)):
        key = raw.strip() if kind == "text" else raw
        probe = ld_decode(key) if kind == "ld" else key
        if key in seen or not is_copy(probe):
            continue
        seen.add(key)
        out.append((kind, key))
    return out
