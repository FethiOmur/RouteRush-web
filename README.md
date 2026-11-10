# RouteRush — web

Marketing site for [RouteRush](https://routerushapp.com), a gamified run and ride
tracking app for iOS. Runs and rides claim H3 hex cells on a 3D globe, earn
Rush Points, and move you through cohort leagues.

This repository holds the marketing site only. The legal pages — privacy policy
and terms of service — live separately in
[`RouteRush-legal`](https://github.com/FethiOmur/RouteRush-legal), because their
URLs are registered with App Store Connect and must not be disturbed by changes
here.

## Structure

```
index.html            self-contained page — inline CSS and JS, no build step
assets/               logo, app icon
assets/fonts/         Splash-Subset.ttf — the brand face, subset (see below)
assets/hero/          two posters only: the hero is a LIVE Mapbox GL map now.
                      poster-start paints before the map, poster-final IS the
                      hero under reduced motion / save-data / no WebGL /
                      software GL / ?nomap=1 (the golden harness runs this
                      mode)
assets/vendor/        mapbox-gl 3.18.0, vendored — the page's only script dep
assets/pins/          the 22 territory owner pins (ring+glow baked in)
assets/territory.geojson  street-snapped conquest loops (build-territory.py)
assets/screens/       app screenshots used in the product sections
```

There is no build pipeline. Since the live-map hero (owner call, 2026-08-11)
the page talks to **api.mapbox.com** at runtime — tiles, glyphs, sprites — and
sends Mapbox's billing pings to events.mapbox.com. One billable "map load" per
visit; 50k/month are free, then $5/1k. Everything else is local, and the
`?nomap=1` mode renders fully offline (poster hero). `?map=force` skips only
the software-GL check (below), so the live map can be exercised in headless
browsers, which render with SwiftShader and otherwise get the poster hero.

### The brand font is subset — regenerate it if you set new text in it

`assets/fonts/Splash-Subset.ttf` contains only the glyphs needed for the string
"RouteRush". The full family is 1.44 MB for 664 glyphs; the page renders seven of
them, so shipping the whole thing meant the brand mark spent 38 seconds in the
system fallback on a throttled phone. The subset is 95 KB and proven identical:
zero differing pixels at 1x, 2x and 3x, identical advance widths.

**If you ever set any other text in the Splash face, those letters will be
missing.** Regenerate from the master, which lives in git history at commit
`316e007` as `assets/fonts/Splash-Regular.ttf`:

```bash
python3 -m fontTools.subset Splash-Regular.ttf --text="RouteRush" --layout-features='*' --notdef-glyph --notdef-outline --output-file=assets/fonts/Splash-Subset.ttf
```

`--layout-features='*'` matters: Splash is a brush script whose `clig`/`dlig`/
`fina`/`salt`/`ss01-03` features substitute alternate glyphs, and the closure is
what keeps `h.fina`, `e.ss01` and the `o_o` ligature in the subset. Keep the
hinting tables (`fpgm`/`prep`/`cvt`) — dropping them is smaller but changes
rasterisation.

### Proving a change is pixel-neutral

`_agent-scratch/perf/golden.mjs` captures 31 deterministic renders across two
viewports; `diff.py` compares two sets and fails on a single differing pixel.
Time-driven things (the topo shader, the rolling start control, reveal
transitions) are frozen before each shot — without that the harness diffs
against itself by millions of pixels.

```bash
python3 -m http.server 8899           # in the project root
node _agent-scratch/perf/golden.mjs before
# ...make the change...
node _agent-scratch/perf/golden.mjs after
python3 _agent-scratch/perf/diff.py before after
```

## Hosting

The site is served by the **`routerush-site` Cloudflare Worker** (static
assets), configured in `wrangler.site.jsonc`. Workers Builds deploys it on
every push to `main` with `npx wrangler deploy --config wrangler.site.jsonc`;
there is no GitHub Pages site any more (moved 2026-11-09: GitHub's certificate
renewal kept failing behind the Cloudflare proxy, which took the site down with
a 526).

- `html_handling: "none"` keeps every URL exactly as its file is named, so
  `/faq.html` stays `/faq.html` (sitemap, canonicals and hreflang depend on it).
- `workers/site.js` only runs when no file matches: it serves `dir/index.html`
  for directory URLs, redirects `/tr` to `/tr/`, and returns `404.html` with a
  404. It also answers Range requests for `*.mp4` with 206, because static
  assets ignore Range and Safari will not play video without it.
- `.assetsignore` keeps repo-only files (`tools/`, `i18n/`, `workers/`, docs,
  configs) off the site. Add new non-site files there.
- `www` is redirected to the apex by a Cloudflare Redirect Rule, not by code.
- `wrangler.toml` is a different Worker: `share-links`, on the narrower routes
  `/post/*`, `/u/*`, `/club/*` and the AASA file. It runs in front of the site
  Worker and falls through to it.

Test the hosting behaviour locally with
`npx wrangler dev --config wrangler.site.jsonc`.

## Running locally

Open `index.html` directly, or serve it if you want to exercise it the way a
browser will in production:

```bash
python3 -m http.server 8899
```

Then visit <http://localhost:8899>.

## Notes for future edits

- **The hero is a live Mapbox GL map flown by scroll.** Native scroll position
  is the only source of truth; one normalized progress value drives the camera
  (`cam(warp(p))` — the measured ARC pacing) and the copy stops. The playhead
  *glides* toward the scroll position (`sequence.glideTauMs`) so a fast flick
  eases instead of teleporting. The loading veil waits only for the opening
  camera (`cam(warp(progress))`, whose low-zoom globe tiles cover the first
  part of the scroll): it lifts on that view's `idle` or after a hard 2.5 s
  cap (`VEIL_CAP_MS`, counted from navigation start), whichever comes first,
  and can never strand the page. On a link slow enough that mapbox-gl.js
  arrives after the cap, the veil is skipped entirely rather than dropped
  over a poster the visitor has already been looking at.
  If the map is not live by then the poster stays visible and the map fades in
  over it once ready (on slow 4G that can take 25 s or more; the poster covers
  it); only a
  chain still not live after 45 s is abandoned for the poster. Deeper tiles
  load on demand — `jumpTo({ preloadOnly: true })` was measured to buy nothing
  in GL JS 3.18, so nothing preloads the corridor. Reduced motion, save-data, missing WebGL,
  software GL (renderer string contains SwiftShader / llvmpipe / Software /
  Microsoft Basic Render, read via `WEBGL_debug_renderer_info` — never the user
  agent; this is what headless crawlers render with) and `?nomap=1` all get the
  poster hero with the same copy and never construct a Mapbox map. `?map=force`
  overrides only the software-GL check. The embedded token is
  a web-only pk token, URL-restricted to routerushapp.com (+ localhost:8899
  for local runs) in the Mapbox console — useless anywhere else. Never embed
  the app's token here: it cannot be URL-restricted without breaking the app.
- **Never set `overflow-x: hidden` on `html`.** It makes `<html>` the scroll
  container and silently breaks the hero's sticky pinning.
- **Glass surfaces** follow the project's own web Liquid Glass system: a tinted
  base with backdrop blur and saturation, a specular sheen composited with
  `screen`, and a masked gradient rim for edge lensing. The nav is fixed, so the
  material reveals itself as content scrolls beneath it.
- **The nav capsule is refractive, not just frosted.** A runtime-generated
  displacement map feeds an SVG `feDisplacementMap` inside `backdrop-filter`,
  so content passing under the rim visibly bends — Chromium only; Safari and
  Firefox fall back to the frosted material automatically. The capsule also
  condenses on scroll (full width at rest, compact pill once scrolling starts),
  and the map regenerates to the new geometry after the transition settles.
- **Colour discipline.** Icons are white. The primary call to action is a white
  capsule with a black label. Cyan `#00E0FF` is an accent only — thin strokes,
  glow, the route line — never an icon fill and never a flooded button.
- `prefers-reduced-motion`, `prefers-reduced-transparency` and `prefers-contrast`
  are all honoured. If glass moves to a different element, update those
  overrides to match.

## Languages

The site ships in the app's six languages: English at the root, plus `/tr/`,
`/it/`, `/de/`, `/es/`, `/fr/`.

**English is the only source.** `index.html` and `faq.html` are written and
edited in English; the other five are generated. Never hand-edit a file under
a locale directory — the next build overwrites it.

```bash
python3 tools/build-locales.py            # regenerate all locales + sitemap.xml
python3 tools/build-locales.py --check    # fail if the committed output is stale
```

Run the build after **any** copy change to `index.html` or `faq.html`, and
commit the regenerated files with it. If an English phrase changed, the build
fails and names it — that failure is the point: it is the only thing standing
between a copy edit and five translations that quietly still say the old
sentence.

Translations live in `i18n/<lang>.json`, keyed by the English text so they can
be read and corrected without touching HTML. Vocabulary is pinned to the app's
own `Localizable.xcstrings` (territory → bölge / territorio / Gebiet /
territorio / territoire) so the site and the product never call the same thing
two different names; `Rush`, `Rush Points`, `Atlas`, `PRO` and `Boldi` stay
English because the app leaves them English. Every locale addresses the reader
informally — `du`, `tu`, `tú` — matching the app.

Two guards exist because both failures actually happened during the build-out:

- **Replacement is confined to text nodes, human-readable attributes and the
  JSON-LD.** A whole-file replace turned `setTimeout` into `setSüreout` and
  killed the map.
- **`<title>` and the meta description must be translated explicitly.** Left to
  word substitution they ship as half-English —
  `RouteRush — Bölge Running App for iOS`. These fields are also where a
  literal rendering is wrong on purpose: the phrase a Turkish runner searches
  for is not a translation of the phrase an English one searches for.

`press.html` is English-only by choice.

## License

All rights reserved.
