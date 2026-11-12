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
shipping a page that quietly says something we retired. The reverse holds too:
English copy with no entry in a locale's file (and not on the i18nlib
allow-list) fails the build instead of shipping untranslated. All locales are
built in memory first and written only if every one succeeded.

Usage:  python3 tools/build-locales.py [--check]
        --check verifies the committed output matches what the sources produce
        and that no stray .html sits in a locale directory
        (for CI, or for answering "did someone hand-edit a generated file?").
"""

import datetime
import hashlib
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
# i18nlib holds the shared notion of what counts as translatable copy, and
# where in a page it can live; the extractor uses the same code.
from i18nlib import (ATTR_RE, LD_CONTENT_FIELDS, LD_FIELD_RE, blank,  # noqa: E402
                     is_copy, ld_decode, scope as _scope,
                     segments as _segments, units)

ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N = ROOT / "i18n"
ORIGIN = "https://routerushapp.com"

PAGES = ["index.html", "faq.html", "credits.html"]
LOCALES = ["tr", "it", "de", "es", "fr"]
# og:locale wants a full tag; hreflang and <html lang> want the short one.
OG_LOCALE = {"en": "en_US", "tr": "tr_TR", "it": "it_IT",
             "de": "de_DE", "es": "es_ES", "fr": "fr_FR"}


def fail(msg):
    print(f"build-locales: {msg}", file=sys.stderr)
    sys.exit(1)


# `&` that does not already start an entity. A translator may write `&amp;` or
# `&nbsp;` on purpose (the keys themselves are raw HTML), so entities pass
# through and only a bare `&` is escaped.
_BARE_AMP = re.compile(r"&(?!(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);)")


def _attr_value(raw, table):
    """What goes between the quotes of an attribute whose source value is `raw`.

    A translation is plain text, not markup: a `"` in it would end the
    attribute early and a bare `&` or `<` would be misread, and the build used
    to exit 0 on that. `'` is left alone (safe inside a double-quoted
    attribute, and escaping it would rewrite every apostrophe in it, fr/it/tr).
    A value equal to its key is the explicit "keep English" and is already
    source HTML, so it is written back untouched.
    """
    v = table.get(raw)
    if v is None or v == raw:
        return raw
    return (_BARE_AMP.sub("&amp;", v).replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _ld_value(raw, table):
    """Same for a JSON-LD string: `raw` is the source's JSON-encoded text, a
    translation is plain text and gets JSON-escaped (`"`, `\\`, newlines).
    Non-ASCII stays literal, exactly as the source writes it."""
    v = table.get(raw)
    if v is None or v == raw:
        return raw
    return json.dumps(v, ensure_ascii=False)[1:-1]


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
            lambda m: f'"{m.group(1)}": "{_ld_value(m.group(2), table)}"', seg)
    return ATTR_RE.sub(
        lambda m: f'{m.group(1)}="{_attr_value(m.group(2), table)}"', seg)


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


def untranslated(scan, table, pattern):
    """English copy in `scan` that the locale neither translates nor keeps.

    The missing-key check above only catches a key that left the source. This
    is the other direction: new English text with no key at all, which would
    ship untranslated while the build passed. Text nodes are checked after the
    phrases the table covers are cut out, so a half-translated node is caught
    too. Allowed: anything with an entry (an entry equal to the English is the
    explicit "keep"), and the shared allow-list in i18nlib (brand, product
    nouns, demo data, numbers, units).
    """
    found = {}
    for kind, raw in units(scan):
        if kind == "text":
            rest = pattern.sub("\x00", raw) if pattern else raw
            for frag in rest.split("\x00"):
                if is_copy(frag):
                    found.setdefault(" ".join(frag.split()), "text")
        elif raw not in table:
            if is_copy(ld_decode(raw) if kind == "ld" else raw):
                found.setdefault(raw, kind)
    return found


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
    scan = src                      # English with the whole-element keys cut out
    for en in [k for k in strings if k.startswith("<")]:
        if src.count(en) != 1:
            fail(f"{lang}/{page}: whole-element key must appear exactly once, "
                 f"found {src.count(en)}:\n  {en[:100]!r}")
        src = src.replace(en, strings[en], 1)
        scan = blank(scan, [en])

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

    # One pass, longest needle first. Sequential str.replace would corrupt
    # overlapping phrases — "Area" is a key and so is "Area captured", and
    # whichever ran first would eat the other. A single regex alternation also
    # guarantees translated output is never rescanned, so a translation that
    # happens to contain an English key cannot be double-replaced.
    pattern = re.compile("|".join(
        re.escape(k) for k in sorted(table, key=len, reverse=True))) if table else None

    stale = untranslated(scan, table, pattern)
    if stale:
        fail(f"{lang}/{page}: {len(stale)} English text(s) have no entry in "
             f"i18n/{lang}.json and would ship untranslated:\n" +
             "\n".join(f"  {t[:80]!r} ({k})" for t, k in stale.items()) +
             f"\n\nTranslate each one. If it is meant to stay English (a name, "
             f"a product noun), add it with the same text as its value, "
             f'e.g. "Name": "Name", so keeping it is a recorded decision.')

    if not pattern:
        return src

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


def rewrite_links(html, lang, page):
    """Fix every path for a page that now lives one directory deeper, and point
    the language switcher's current entry at itself."""
    # Assets are root-absolute so no per-depth arithmetic is needed.
    html = re.sub(r'(?<=["\'(])assets/', '/assets/', html)
    # faq.html is translated, so stay inside the locale; press.html is not.
    html = html.replace('href="faq.html"', f'href="/{lang}/faq.html"')
    html = html.replace('href="press.html"', 'href="/press.html"')
    # credits.html is translated around a licence notice that stays English.
    html = html.replace('href="credits.html"', f'href="/{lang}/credits.html"')
    # App Store CTAs: each locale reports as its own App Analytics campaign,
    # so installs can be read per market (see the note above the nav CTA).
    html = html.replace('ct=web-en&amp;', f'ct=web-{lang}&amp;')
    # Home links point at the locale's own front page. Match the bare anchor
    # only: the language switcher's English entry carries hreflang/aria
    # attributes and the JS language hint carries an id, so neither matches and
    # visitors can still leave the locale. Matching on the anchor rather than
    # its text matters: this runs after translation, when "Home" has already
    # become "Ana sayfa" (only Italian kept "Home", so only Italian worked).
    html = html.replace('<a href="/">', f'<a href="/{lang}/">')
    # Language switcher: current locale is marked and inert, English loses the
    # marker it carries in the source.
    html = html.replace(' href="/" hreflang="en" aria-current="page"',
                        ' href="/" hreflang="en"', 1)
    html = html.replace(f' href="/{lang}/" hreflang="{lang}"',
                        f' href="/{lang}/" hreflang="{lang}" aria-current="page"', 1)
    # The FAQ and credits language rows link to the same page in each locale.
    html = html.replace(f' href="/{page}" hreflang="en" aria-current="page"',
                        f' href="/{page}" hreflang="en"', 1)
    html = html.replace(f' href="/{lang}/{page}" hreflang="{lang}"',
                        f' href="/{lang}/{page}" hreflang="{lang}" aria-current="page"', 1)
    return html


def build(lang, page):
    """The generated page as a string. Nothing is read from or written to the
    locale directories here: main() builds every page first and writes only if
    all of them succeeded."""
    src = (ROOT / page).read_text(encoding="utf-8")
    locale_file = I18N / f"{lang}.json"
    if not locale_file.exists():
        fail(f"missing {locale_file.relative_to(ROOT)}")
    strings = json.loads(locale_file.read_text(encoding="utf-8")).get(page)
    if not strings:
        fail(f"i18n/{lang}.json has no entry for {page}")

    html = apply_strings(src, strings, lang, page)
    # Checked here rather than after rewrite_head, because that function edits
    # @id and inLanguage on purpose and asserts its own edits one by one. This
    # is the translation step's own invariant: it may change copy, nothing else.
    assert_ldjson_structure_survived(src, html, lang, page)
    html = rewrite_head(html, lang, page)
    html = rewrite_links(html, lang, page)
    return html


def render_sitemap(check, generated):
    """Render the sitemap with the full hreflang cluster on every entry.

    Google wants the alternates declared in at least one place; declaring them
    in both the HTML head and the sitemap is the belt-and-braces version and
    costs nothing. Generated rather than hand-kept for the same reason the
    pages are: adding a locale should not be an invitation to forget a file.

    `generated` maps each locale page's path to the text about to be written,
    so lastmod hashes what the build produced rather than what is on disk.
    Returns (xml, manifest, dirty); the caller writes.
    """
    manifest = json.loads(LASTMOD_FILE.read_text()) if LASTMOD_FILE.exists() else {}
    dirty = False

    def lastmod(rel):
        """lastmod of one served file: kept while its bytes are unchanged,
        moved to today when they change. A content hash rather than git dates,
        because a git date changes with the very commit that records it, which
        would make --check fail right after every commit."""
        nonlocal dirty
        data = (generated[rel].encode("utf-8") if rel in generated
                else (ROOT / rel).read_bytes())
        digest = hashlib.sha256(data).hexdigest()
        entry = manifest.get(rel)
        if entry and entry["sha256"] == digest:
            return entry["lastmod"]
        if check:
            fail(f"{rel} changed since its sitemap lastmod was recorded "
                 f"— run the build")
        manifest[rel] = {"sha256": digest,
                         "lastmod": datetime.date.today().isoformat()}
        dirty = True
        return manifest[rel]["lastmod"]

    def served_file(lang, page):
        return page if lang == "en" else f"{lang}/{page}"

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
            lines.append(f"    <lastmod>{lastmod(served_file(lang, page))}</lastmod>")
            lines.append("  </url>")
    # press.html is English-only on purpose: journalists asking for assets are
    # not the audience a translation serves, and a stale one would be worse.
    # privacy/terms are English-only for a different reason: a translated
    # contract raises the question of which language governs, and the answer
    # "the English one" is worth more than the convenience of six copies.
    for page in ("press.html", "privacy.html", "terms.html"):
        lines.append("  <url>")
        lines.append(f"    <loc>{ORIGIN}/{page}</loc>")
        lines.append(f"    <lastmod>{lastmod(page)}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    xml = "\n".join(lines) + "\n"

    return xml, manifest, dirty


# Per-file sitemap lastmod, keyed by served path: {"sha256": ..., "lastmod": ...}.
LASTMOD_FILE = ROOT / "tools" / "lastmod.json"


def write_all(files):
    """Write every file, each through a temp file and an atomic rename."""
    for path, text in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)


def unexpected_html():
    """.html files inside a locale directory that no page of the build makes."""
    return [p for lang in LOCALES for p in sorted((ROOT / lang).rglob("*.html"))
            if p.relative_to(ROOT / lang).as_posix() not in PAGES]


def main():
    check = "--check" in sys.argv

    # Build everything in memory first: an error in any locale must leave every
    # file on disk exactly as it was, not half-regenerated.
    generated = {}
    for lang in LOCALES:
        for page in PAGES:
            generated[f"{lang}/{page}"] = build(lang, page)
    xml, manifest, dirty = render_sitemap(check, generated)

    extra = unexpected_html()
    if check:
        if extra:
            fail("unexpected .html in a locale directory (the build does not "
                 "make it, and a stale copy would be served): " +
                 ", ".join(str(p.relative_to(ROOT)) for p in extra))
        for rel, html in generated.items():
            out = ROOT / rel
            if not out.exists():
                fail(f"{rel} is missing — run the build")
            if out.read_text(encoding="utf-8") != html:
                fail(f"{rel} differs from what the sources produce — it was "
                     f"hand-edited, or the build was not re-run")
        if (ROOT / "sitemap.xml").read_text(encoding="utf-8") != xml:
            fail("sitemap.xml differs from what the sources produce")
        print(f"build-locales: OK — {len(LOCALES) * len(PAGES)} generated files "
              f"and sitemap.xml match their sources")
        return

    for p in extra:
        print(f"build-locales: warning: {p.relative_to(ROOT)} is not generated "
              f"and is not removed here; delete it", file=sys.stderr)
    files = [(ROOT / rel, html) for rel, html in generated.items()]
    files.append((ROOT / "sitemap.xml", xml))
    if dirty:
        files.append((LASTMOD_FILE, json.dumps(manifest, indent=2, sort_keys=True) + "\n"))
    write_all(files)
    for rel in generated:
        print(f"  wrote {rel}")
    print(f"build-locales: {len(generated)} files from {len(PAGES)} sources")


if __name__ == "__main__":
    main()
