#!/usr/bin/env python3
"""Emit a translation skeleton for one page, in the form the builder reads.

Keys are the English exactly as the builder looks them up (see i18nlib): the
stripped text of a text node, the whole value of an attribute or JSON-LD
content field, and the whole-element keys for sentences split across markup.
The builder replaces every occurrence of a key, so there is nothing to widen or
disambiguate. What counts as copy, and where it can live, comes from i18nlib,
the same code the builder uses, so this cannot propose a key the builder would
reject.

Every value is pre-filled with the English, which the builder accepts as an
explicit "keep": replace each value with the translation. Whatever you leave
equal to its key stays English on purpose.

Usage:  python3 tools/extract-strings.py index.html > /tmp/skeleton.json
"""

import html as htmlmod
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from i18nlib import candidates, ld_decode  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    page = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    src = (ROOT / page).read_text(encoding="utf-8")
    skeleton = {}
    for kind, key in candidates(src):
        # Text and whole-element keys are inserted as HTML, so their value
        # starts as the same HTML. An attribute or JSON-LD value is plain text
        # to the builder, which escapes it, so the translator gets it decoded.
        if kind == "attr":
            skeleton[key] = htmlmod.unescape(key)
        elif kind == "ld":
            skeleton[key] = ld_decode(key)
        else:
            skeleton[key] = key
    print(json.dumps({page: skeleton}, ensure_ascii=False, indent=2))
    print(f"// {len(skeleton)} translatable fragments in {page}", file=sys.stderr)


if __name__ == "__main__":
    main()
