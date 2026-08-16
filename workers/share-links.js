/**
 * Share-link landing pages for routerushapp.com/post/* and /u/*.
 *
 * WHY THIS EXISTS
 * The site is static on GitHub Pages, which cannot serve a path it has no file
 * for: /post/<uuid> returned a hard 404, so every link the app shared was a
 * dead link. GitHub Pages' 404.html trick would render something, but the HTTP
 * status stays 404 and link unfurlers (iMessage, WhatsApp, X) treat that as
 * broken. The domain already proxies through Cloudflare, so a Worker in front
 * of the origin can answer these two paths with a real 200 and real Open Graph
 * tags, and pass everything else through untouched.
 *
 * WHAT IT DELIBERATELY DOES NOT DO
 * It never reads the post. Shared posts are viewable in the app only (owner
 * decision), so this Worker holds no database credentials, makes no outbound
 * call, and leaks nothing about who shared what — the id in the URL is all it
 * sees and all it echoes back, and it echoes it back only into a deep link.
 *
 * ONCE UNIVERSAL LINKS ARE CONFIGURED this page mostly stops being seen: iOS
 * intercepts the URL and opens the app before a browser ever loads it. It stays
 * as the answer for everyone else — Android, desktop, anyone without the app.
 */

const ORIGIN_PASSTHROUGH = ["/post/", "/u/"];
const APP_STORE_URL = "https://apps.apple.com/app/id6783352912";
const SITE = "https://routerushapp.com";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    const isShare = ORIGIN_PASSTHROUGH.some((p) => path.startsWith(p));
    if (!isShare) return fetch(request);

    // /post/<id> and /u/<handle>. Anything deeper is not a share link.
    const [, kind, ...rest] = path.split("/");
    const slug = decodeURIComponent(rest.join("/")).trim();
    if (!slug || rest.length > 1) return fetch(request);

    const isProfile = kind === "u";
    const title = isProfile
      ? "A runner on RouteRush"
      : "A run shared from RouteRush";
    const blurb = isProfile
      ? "Open RouteRush to see their territory, their league and the ground they hold."
      : "Open RouteRush to see the run, the ground it claimed and where it sits on the map.";

    // Only ever reflected into an app-scheme URL, never into HTML text, but
    // escaped anyway so a crafted link cannot smuggle markup into the page.
    const safeSlug = slug.replace(/[^A-Za-z0-9._~-]/g, "");
    const deepLink = isProfile
      ? `routerush://u/${safeSlug}`
      : `routerush://post/${safeSlug}`;

    const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self' ${SITE}; style-src 'unsafe-inline'; img-src ${SITE}; font-src ${SITE}; script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="robots" content="noindex">
<title>${title} — RouteRush</title>
<meta name="description" content="${blurb}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="RouteRush">
<meta property="og:title" content="${title}">
<meta property="og:description" content="${blurb}">
<meta property="og:url" content="${SITE}${path}">
<meta property="og:image" content="${SITE}/assets/og.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${title}">
<meta name="twitter:description" content="${blurb}">
<meta name="twitter:image" content="${SITE}/assets/og.jpg">
<link rel="icon" href="${SITE}/assets/favicon.svg?v=2" type="image/svg+xml">
<link rel="icon" href="${SITE}/assets/favicon.png" sizes="512x512" type="image/png">
<link rel="apple-touch-icon" sizes="180x180" href="${SITE}/assets/apple-touch-icon.png">
<style>
  @font-face { font-family:'Splash'; src:url('${SITE}/assets/fonts/Splash-Subset.ttf') format('truetype'); font-display:block; }
  *{margin:0;padding:0;box-sizing:border-box}
  html{color-scheme:dark}
  body{background:#000;color:#fff;min-height:100svh;display:grid;place-items:center;padding:32px;
       font:16px/1.6 -apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif;
       -webkit-font-smoothing:antialiased;text-align:center}
  .card{max-width:420px}
  .mark{font-family:'Splash',cursive;font-size:44px;line-height:1;margin-bottom:22px}
  .mark a{color:#fff;text-decoration:none}
  h1{font-size:24px;font-weight:600;letter-spacing:-.2px;margin-bottom:10px}
  p{color:rgba(255,255,255,.62);margin-bottom:26px}
  .btn{display:block;padding:14px 20px;border-radius:999px;text-decoration:none;font-weight:560}
  .primary{background:#fff;color:#000;margin-bottom:10px}
  .ghost{border:1px solid rgba(255,255,255,.16);color:#fff}
  .foot{margin-top:26px;font-size:13px;color:rgba(255,255,255,.38)}
  .foot a{color:inherit}
</style>
</head>
<body>
  <div class="card">
    <div class="mark"><a href="${SITE}/">RouteRush</a></div>
    <h1>${title}</h1>
    <p>${blurb}</p>
    <a class="btn primary" href="${deepLink}">Open in RouteRush</a>
    <a class="btn ghost" href="${APP_STORE_URL}">Get RouteRush</a>
    <p class="foot"><a href="${SITE}/">routerushapp.com</a></p>
  </div>
</body>
</html>`;

    return new Response(html, {
      status: 200,
      headers: {
        "content-type": "text/html; charset=utf-8",
        // Short: the page is static per id, but the copy may change and these
        // URLs are hit by unfurlers that cache aggressively.
        "cache-control": "public, max-age=300",
        "referrer-policy": "strict-origin-when-cross-origin",
        "x-content-type-options": "nosniff",
      },
    });
  },
};
