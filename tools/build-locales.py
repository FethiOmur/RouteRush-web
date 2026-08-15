#!/usr/bin/env python3
"""Generate the localized copies of the site from the English source.

Why a build step instead of six hand-kept files: the landing page is ~2500
lines and its copy is under a standing rule that the canonical one-liner must
read identically on every surface. Six hand-maintained translations drift on
the first copy edit, silently, and nobody notices until a visitor reads a
sentence we retired a month ago. Here English is the only source; the
translations are data, keyed by the English text itself so the files stay
readable to a human reviewer.

The safety property that makes this trustworthy: every English key must still
be present in the source. If it is gone the copy was edited and the
translation is now stale, so the build fails and refuses to write rather than
shipping a page that quietly says something we retired.

Usage:  python3 tools/build-locales.py [--check]
        --check verifies the committed output matches what the sources produce
        (for CI, or for answering "did someone hand-edit a generated file?").
"""

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# (i18nlib holds the shared notion of what counts as translatable copy)

ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N = ROOT / "i18n"
ORIGIN = "https://routerushapp.com"

PAGES = ["index.html", "faq.html"]
LOCALES = ["tr", "it", "de", "es", "fr"]
# og:locale wants a full tag; hreflang and <html lang> want the short one.
OG_LOCALE = {"en": "en_US", "tr": "tr_TR", "it": "it_IT",
             "de": "de_DE", "es": "es_ES", "fr": "fr_FR"}


def fail(msg):
    print(f"build-locales: {msg}", file=sys.stderr)
    sys.exit(1)


# Regions that are code, not copy. A naive whole-file replace turns
# `setTimeout` into `setSüreout` and `TerritoryRenderer` into `BölgeRenderer`,
# because "Time" and "Territory" are both legitimate copy elsewhere on the
# page. That shipped once in development and killed the map outright, so the
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


def _segments(src):
    """Yield (text, translatable) pairs covering the whole document."""
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


def _apply_to_segment(seg, kind, sub, table):
    """Text nodes get phrase substitution; attributes get whole-value lookup.

    An attribute is not prose, it is a single label, and substituting phrases
    inside one produces half-English output nobody can see: `aria-label="Pause
    control"` picked up the word-level key "Pause" and shipped `"Duraklat
    control"` to five locales for weeks, invisible in every screenshot because
    only a screen reader ever reads it. So an attribute is translated only when
    its entire value is a key — the same all-or-nothing rule the head fields
    already live under. Audited before the change: across index.html and
    faq.html this affected exactly three values in tr (two in de and fr), all
    of them damage, and no attribute anywhere relied on substring replacement
    to produce something wanted.
    """
    if kind is False:
        return seg
    if kind is True:
        return sub(seg)
    if kind == "ldjson":
        return LD_FIELD_RE.sub(
            lambda m: f'"{m.group(1)}": "{table.get(m.group(2), m.group(2))}"', seg)
    return ATTR_RE.sub(
        lambda m: f'{m.group(1)}="{table.get(m.group(2), m.group(2))}"', seg)


def _scope(src):
    """(prose, whole-value slots) — the two ways a translation can land.

    They are kept apart because they match by different rules: prose by
    substring, an attribute or a JSON-LD content field only as a whole value.
    Flattening them into one blob is what let a key that exists solely inside a
    longer attribute look present while never actually being applied.
    """
    prose, exact = [], []
    for seg, kind in _segments(src):
        if kind is True:
            prose.append(seg)
        elif kind == "attrs":
            exact.extend(m.group(2) for m in ATTR_RE.finditer(seg))
        elif kind == "ldjson":
            exact.extend(m.group(2) for m in LD_FIELD_RE.finditer(seg))
    return "\n".join(prose), exact


def translatable_text(src):
    """Everything a translation is allowed to touch, concatenated."""
    prose, exact = _scope(src)
    return "\n".join([prose] + exact)


def assert_ldjson_structure_survived(src, out, lang, page):
    """Structured data is vocabulary, not language: only copy may differ.

    Walks both documents' JSON-LD and requires an identical shape — same nodes,
    same keys, same values everywhere except the whitelisted content fields.
    This is the check that would have caught `FAQPage` becoming `SSSPage` on
    day one, and it is cheap enough to run on every build. A schema error is
    invisible by construction: the page looks right, the markup parses as JSON,
    and only the rich result quietly never appears.
    """
    def blocks(html):
        return [json.loads(re.sub(r'^<script[^>]*>|</script>$', '', s, flags=re.S))
                for s in re.findall(
                    r'<script type="application/ld\+json">.*?</script>', html, re.S)]

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from walk(v, f"{path}[{i}]")
        else:
            yield path, node

    a, b = blocks(src), blocks(out)
    if len(a) != len(b):
        fail(f"{lang}/{page}: JSON-LD block count changed, {len(a)} -> {len(b)}")
    for src_block, out_block in zip(a, b):
        sm, om = dict(walk(src_block)), dict(walk(out_block))
        if sm.keys() != om.keys():
            gone = sorted(set(sm) ^ set(om))[:5]
            fail(f"{lang}/{page}: JSON-LD shape changed at {gone}")
        for path, value in sm.items():
            field = path.rsplit(".", 1)[-1].split("[")[0]
            if field in LD_CONTENT_FIELDS:
                continue
            if om[path] != value:
                fail(f"{lang}/{page}: JSON-LD structure was translated at "
                     f"{path}: {value!r} -> {om[path]!r}. Only "
                     f"{LD_CONTENT_FIELDS} carry copy; everything else is "
                     f"schema.org vocabulary and must survive verbatim.")


def require_head_copy(src, strings, lang, page):
    """The head fields must be translated deliberately, never word-by-word.

    Left to the general replacement, `<title>RouteRush — Territory Running App
    for iOS</title>` picks up the locale's word for "Territory" and ships
    "RouteRush — Bölge Running App for iOS" — half-translated, and the single
    most visible string the site has. These are also the fields where a literal
    rendering is wrong on purpose: the phrase a Turkish runner searches for is
    not a translation of the phrase an English one searches for. So each is
    required to be present as its own key.
    """
    fields = re.findall(r'<title>([^<]+)</title>', src)
    fields += re.findall(
        r'<meta (?:name|property)="(?:description|og:title|og:description|'
        r'og:image:alt|twitter:title|twitter:description)" content="([^"]+)"', src)
    absent = [f for f in dict.fromkeys(fields) if f not in strings]
    if absent:
        fail(f"{lang}/{page}: {len(absent)} head field(s) have no deliberate "
             f"translation:\n" + "\n".join(f"  {a[:90]!r}" for a in absent) +
             f"\n\nAdd them to i18n/{lang}.json. Without an explicit entry they "
             f"get word-substituted into half-English titles.")


def apply_strings(src, strings, lang, page):
    """Swap English copy for the locale's, failing loudly on any drift."""
    require_head_copy(src, strings, lang, page)
    # Whole-element keys first, against the raw source. A sentence split across
    # markup — `Running is how<br>you take <em>ground.</em>` — has to be handed
    # to the translator in one piece, or they are forced to reproduce English
    # word order across three fragments. Such a key spans tag boundaries, so it
    # cannot match inside a text node and is applied here instead. The author
    # writes these deliberately (they contain markup), so an exact single match
    # is required.
    for en in [k for k in strings if k.startswith("<")]:
        if src.count(en) != 1:
            fail(f"{lang}/{page}: whole-element key must appear exactly once, "
                 f"found {src.count(en)}:\n  {en[:100]!r}")
        src = src.replace(en, strings[en], 1)

    prose, attr_values = _scope(src)
    missing, table, repeated = [], {}, []
    for en, localized in strings.items():
        if en.startswith("//") or en.startswith("<"):
            continue
        # Counted the way it is applied: anywhere in prose, but in an attribute
        # only as the whole value. A key that exists solely as a fragment of a
        # longer attribute would otherwise be reported present and never be
        # applied — a silent no-op, the failure mode this file keeps closing.
        n = prose.count(en) + attr_values.count(en)
        if n == 0:
            missing.append(en)
            continue
        # A phrase that appears more than once — "Territory" in the nav and on
        # the leaderboard tab, "Download on the App Store" at both ends of the
        # page — means the same thing in each place and gets the same
        # translation in each place. Anchoring to one occurrence was the first
        # design and it shipped a page with a translated tab above an
        # untranslated nav, so every occurrence changes and the count is
        # reported instead of hidden.
        if n > 1:
            repeated.append((en, n))
        table[en] = localized

    if repeated and "--verbose" in sys.argv:
        print(f"  {lang}/{page}: {len(repeated)} phrase(s) replaced everywhere: "
              + ", ".join(f"{e[:24]!r}×{n}" for e, n in repeated))

    if missing:
        fail(f"{lang}/{page}: {len(missing)} phrase(s) are no longer in the "
             f"English source:\n" +
             "\n".join(f"  {m[:80]!r}" for m in missing) +
             f"\n\nThe English copy changed. Update i18n/*.json for every "
             f"locale before shipping, or the translations go stale silently.")

    if not table:
        return src

    # One pass, longest needle first. Sequential str.replace would corrupt
    # overlapping phrases — "Area" is a key and so is "Area captured", and
    # whichever ran first would eat the other. A single regex alternation also
    # guarantees translated output is never rescanned, so a translation that
    # happens to contain an English key cannot be double-replaced.
    pattern = re.compile("|".join(
        re.escape(k) for k in sorted(table, key=len, reverse=True)))

    def sub(text):
        return pattern.sub(lambda m: table[m.group(0)], text)

    return "".join(_apply_to_segment(seg, kind, sub, table)
                   for seg, kind in _segments(src))


def rewrite_head(html, lang, page):
    """Per-locale identity. Content is already translated by this point.

    canonical and og:url must point at the locale's own URL. A locale page that
    canonicals to the English root is telling Google "I am a duplicate of that"
    — Google obeys, drops it, and the translation never appears in search.
    """
    path = f"/{lang}/" if page == "index.html" else f"/{lang}/{page}"
    url = ORIGIN + path

    # Every rewrite here asserts it actually matched. This is not defensive
    # habit — it is a bug that shipped: the old code also tried to rewrite
    # `"inLanguage": "en"`, the source had written it as an array, and the
    # replacement silently did nothing for weeks. A no-op that looks like a
    # success is the worst failure mode a generator has, and the translation
    # path already refused to allow it while the head path did not.
    def sub1(pattern, repl, s, what):
        out, n = re.subn(pattern, repl, s, count=1)
        if n != 1:
            fail(f"{lang}/{page}: expected exactly one {what} to rewrite, "
                 f"matched {n}. The source head changed shape — fix this "
                 f"function rather than letting the rewrite quietly skip.")
        return out

    html = sub1(r'<html lang="en">', f'<html lang="{lang}">', html, "<html lang>")
    html = sub1(r'<link rel="canonical" href="[^"]*">',
                f'<link rel="canonical" href="{url}">', html, "canonical")
    html = sub1(r'<meta property="og:url" content="[^"]*">',
                f'<meta property="og:url" content="{url}">', html, "og:url")
    html = sub1(r'<meta property="og:locale" content="[^"]*">',
                f'<meta property="og:locale" content="{OG_LOCALE[lang]}">',
                html, "og:locale")
    # The FAQ's own language, which is the page's. Deliberately NOT the app's
    # `inLanguage` array on the MobileApplication node: that lists the six
    # languages the product ships in and is the same claim on every page.
    if page == "faq.html":
        html = sub1(r'"inLanguage": "en"', f'"inLanguage": "{lang}"',
                    html, "FAQPage inLanguage")
        # Each translation is its own node. Sharing one @id across six pages
        # would assert they are the same thing, which is exactly the claim
        # hreflang exists to deny. isPartOf/about keep pointing at the site
        # and app nodes, which genuinely are shared.
        html = sub1(r'"@id": "https://routerushapp\.com/faq\.html#faq"',
                    f'"@id": "{ORIGIN}/{lang}/faq.html#faq"', html, "FAQPage @id")
    return html


def rewrite_links(html, lang):
    """Fix every path for a page that now lives one directory deeper, and point
    the language switcher's current entry at itself."""
    # Assets are root-absolute so no per-depth arithmetic is needed.
    html = re.sub(r'(?<=["\'(])assets/', '/assets/', html)
    # faq.html is translated, so stay inside the locale; press.html is not.
    html = html.replace('href="faq.html"', f'href="/{lang}/faq.html"')
    html = html.replace('href="press.html"', 'href="/press.html"')
    # Home links point at the locale's own front page — but only these specific
    # ones. A blanket href="/" rewrite would also hit the language switcher's
    # English entry and strand every visitor inside one locale.
    html = html.replace('<a href="/">Home</a>', f'<a href="/{lang}/">Home</a>')
    html = html.replace('<div class="wordmark"><a href="/">',
                        f'<div class="wordmark"><a href="/{lang}/">')
    html = html.replace('<p class="cta">See the map for yourself — <a href="/">',
                        f'<p class="cta">See the map for yourself — <a href="/{lang}/">')
    # Language switcher: current locale is marked and inert, English loses the
    # marker it carries in the source.
    html = html.replace(' href="/" hreflang="en" aria-current="page"',
                        ' href="/" hreflang="en"', 1)
    html = html.replace(f' href="/{lang}/" hreflang="{lang}"',
                        f' href="/{lang}/" hreflang="{lang}" aria-current="page"', 1)
    return html


def build(lang, page, check):
    src = (ROOT / page).read_text()
    locale_file = I18N / f"{lang}.json"
    if not locale_file.exists():
        fail(f"missing {locale_file.relative_to(ROOT)}")
    strings = json.loads(locale_file.read_text()).get(page)
    if not strings:
        fail(f"i18n/{lang}.json has no entry for {page}")

    html = apply_strings(src, strings, lang, page)
    # Checked here rather than after rewrite_head, because that function edits
    # @id and inLanguage on purpose and asserts its own edits one by one. This
    # is the translation step's own invariant: it may change copy, nothing else.
    assert_ldjson_structure_survived(src, html, lang, page)
    html = rewrite_head(html, lang, page)
    html = rewrite_links(html, lang)

    out = ROOT / lang / page
    if check:
        if not out.exists():
            fail(f"{out.relative_to(ROOT)} is missing — run the build")
        if out.read_text() != html:
            fail(f"{out.relative_to(ROOT)} differs from what the sources "
                 f"produce — it was hand-edited, or the build was not re-run")
        return None
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    return out


def write_sitemap(check):
    """Emit the sitemap with the full hreflang cluster on every entry.

    Google wants the alternates declared in at least one place; declaring them
    in both the HTML head and the sitemap is the belt-and-braces version and
    costs nothing. Generated rather than hand-kept for the same reason the
    pages are: adding a locale should not be an invitation to forget a file.
    """
    today = (ROOT / "sitemap.xml").exists() and re.search(
        r"<lastmod>([\d-]+)</lastmod>", (ROOT / "sitemap.xml").read_text())
    stamp = LASTMOD or (today.group(1) if today else "2026-08-13")

    langs = ["en"] + LOCALES
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
             '        xmlns:xhtml="http://www.w3.org/1999/xhtml">']

    def url_for(lang, page):
        base = ORIGIN + ("/" if lang == "en" else f"/{lang}/")
        return base if page == "index.html" else base + page

    for page in PAGES:
        for lang in langs:
            lines.append("  <url>")
            lines.append(f"    <loc>{url_for(lang, page)}</loc>")
            for alt in langs:
                lines.append(f'    <xhtml:link rel="alternate" hreflang="{alt}" '
                             f'href="{url_for(alt, page)}"/>')
            lines.append('    <xhtml:link rel="alternate" hreflang="x-default" '
                         f'href="{url_for("en", page)}"/>')
            lines.append(f"    <lastmod>{stamp}</lastmod>")
            lines.append("  </url>")
    # press.html is English-only on purpose: journalists asking for assets are
    # not the audience a translation serves, and a stale one would be worse.
    # privacy/terms are English-only for a different reason: a translated
    # contract raises the question of which language governs, and the answer
    # "the English one" is worth more than the convenience of six copies.
    for page in ("press.html", "privacy.html", "terms.html"):
        lines.append("  <url>")
        lines.append(f"    <loc>{ORIGIN}/{page}</loc>")
        lines.append(f"    <lastmod>{stamp}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    xml = "\n".join(lines) + "\n"

    out = ROOT / "sitemap.xml"
    if check:
        if out.read_text() != xml:
            fail("sitemap.xml differs from what the sources produce")
        return None
    out.write_text(xml)
    return out


LASTMOD = None   # set with --lastmod=YYYY-MM-DD when the copy actually changed


def main():
    global LASTMOD
    for a in sys.argv:
        if a.startswith("--lastmod="):
            LASTMOD = a.split("=", 1)[1]
    check = "--check" in sys.argv
    written = []
    for lang in LOCALES:
        for page in PAGES:
            r = build(lang, page, check)
            if r:
                written.append(r.relative_to(ROOT))
    write_sitemap(check)
    if check:
        print(f"build-locales: OK — {len(LOCALES) * len(PAGES)} generated files "
              f"and sitemap.xml match their sources")
    else:
        for w in written:
            print(f"  wrote {w}")
        print(f"build-locales: {len(written)} files from {len(PAGES)} sources")


if __name__ == "__main__":
    main()
