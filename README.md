# RouteRush — web

Marketing site for [RouteRush](https://routerush.app), a gamified run and ride
tracking app for iOS. Runs and rides claim H3 hex cells on a Mapbox globe, earn
Rush Points, and move you through cohort leagues.

This repository holds the marketing site only. The legal pages — privacy policy
and terms of service — live separately in
[`RouteRush-legal`](https://github.com/FethiOmur/RouteRush-legal), because their
URLs are registered with App Store Connect and must not be disturbed by changes
here.

## Structure

```
index.html         self-contained page — inline CSS and JS, no build step
assets/            logo, app icon
assets/screens/    app screenshots used in the product sections
```

There are no dependencies, no build pipeline, and **no network requests at
runtime** — every asset is local, so the page renders identically offline.

## Running locally

Open `index.html` directly, or serve it if you want to exercise it the way a
browser will in production:

```bash
python3 -m http.server 8899
```

Then visit <http://localhost:8899>.

## Notes for future edits

- **The hero is a scroll-scrubbed sequence.** Native scroll position is the only
  source of truth; one normalized progress value drives the canvas, the copy
  stops, and the counters. It must stay deterministic in both directions — the
  same scroll offset always produces the same frame.
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

## License

All rights reserved.
