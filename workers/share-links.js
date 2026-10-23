/**
 * Share-link landing pages for routerushapp.com/post/*, /u/* and /club/*.
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
 * (Club pages are the one exception: /club/<id> reads the club's public row —
 * name, member count, city, cover — for the link preview. See lookupClub.)
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
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Club links: /club/<clubId> and /club/<clubId>/event/<eventId>. Copy exists in
// the app's six languages; the language comes from Accept-Language (or an
// explicit ?lang=), never from a cookie or a stored profile, so nothing about
// the visitor is kept. Club and event content is members-only, so the page
// says nothing about the club beyond "a club" / "a club event".
const CLUB_COPY = {
  en: {
    club: ["A club on RouteRush", "Open RouteRush to see the club, its members and the ground it has claimed. Club content is visible in the app only."],
    event: ["A club event on RouteRush", "Open RouteRush to see the event and who is going. Club content is visible in the app only."],
    open: "Open in RouteRush", get: "Get RouteRush",
  },
  tr: {
    club: ["RouteRush'ta bir kulüp", "Kulübü, üyelerini ve ele geçirdiği bölgeleri görmek için RouteRush'ı aç. Kulüp içerikleri yalnızca uygulamada görünür."],
    event: ["RouteRush'ta bir kulüp etkinliği", "Etkinliği ve kimlerin katıldığını görmek için RouteRush'ı aç. Kulüp içerikleri yalnızca uygulamada görünür."],
    open: "RouteRush'ta aç", get: "RouteRush'ı indir",
  },
  it: {
    club: ["Un club su RouteRush", "Apri RouteRush per vedere il club, i suoi membri e i territori conquistati. I contenuti del club sono visibili solo nell'app."],
    event: ["Un evento del club su RouteRush", "Apri RouteRush per vedere l'evento e chi partecipa. I contenuti del club sono visibili solo nell'app."],
    open: "Apri in RouteRush", get: "Scarica RouteRush",
  },
  de: {
    club: ["Ein Club auf RouteRush", "Öffne RouteRush, um den Club, seine Mitglieder und seine Gebiete zu sehen. Club-Inhalte sind nur in der App sichtbar."],
    event: ["Ein Club-Event auf RouteRush", "Öffne RouteRush, um das Event und die Teilnehmer zu sehen. Club-Inhalte sind nur in der App sichtbar."],
    open: "In RouteRush öffnen", get: "RouteRush laden",
  },
  es: {
    club: ["Un club en RouteRush", "Abre RouteRush para ver el club, sus miembros y los territorios que ha conquistado. El contenido del club solo se ve en la app."],
    event: ["Un evento de club en RouteRush", "Abre RouteRush para ver el evento y quién va. El contenido del club solo se ve en la app."],
    open: "Abrir en RouteRush", get: "Descargar RouteRush",
  },
  fr: {
    club: ["Un club sur RouteRush", "Ouvre RouteRush pour voir le club, ses membres et les territoires conquis. Le contenu du club n'est visible que dans l'app."],
    event: ["Un événement de club sur RouteRush", "Ouvre RouteRush pour voir l'événement et qui y participe. Le contenu du club n'est visible que dans l'app."],
    open: "Ouvrir dans RouteRush", get: "Télécharger RouteRush",
  },
};
// Link-preview copy for a club the Worker could look up. {name} is the club
// name, {n} the member count, {city} the city (omitted when the club has none).
const CLUB_PREVIEW = {
  en: { title: "Join {name} on RouteRush", members: ["{n} member", "{n} members"] },
  tr: { title: "{name} kulübüne RouteRush'ta katıl", members: ["{n} üye", "{n} üye"] },
  it: { title: "Unisciti a {name} su RouteRush", members: ["{n} membro", "{n} membri"] },
  de: { title: "Tritt {name} auf RouteRush bei", members: ["{n} Mitglied", "{n} Mitglieder"] },
  es: { title: "Únete a {name} en RouteRush", members: ["{n} miembro", "{n} miembros"] },
  fr: { title: "Rejoins {name} sur RouteRush", members: ["{n} membre", "{n} membres"] },
};
const LANG_NAMES = { en: "English", tr: "Türkçe", it: "Italiano", de: "Deutsch", es: "Español", fr: "Français" };

function pickLang(request, url) {
  const forced = (url.searchParams.get("lang") || "").toLowerCase();
  if (CLUB_COPY[forced]) return forced;
  // "tr-TR,tr;q=0.9,en;q=0.8" -> first supported primary tag by q-value order.
  const ranked = (request.headers.get("accept-language") || "")
    .split(",")
    .map((part) => {
      const [tag, ...params] = part.trim().split(";");
      const q = params.map((x) => x.trim()).find((x) => x.startsWith("q="));
      return { lang: tag.trim().toLowerCase().split("-")[0], q: q ? parseFloat(q.slice(2)) || 0 : 1 };
    })
    .filter((x) => x.lang)
    .sort((a, b) => b.q - a.q);
  const hit = ranked.find((x) => CLUB_COPY[x.lang]);
  return hit ? hit.lang : "en";
}

function esc(text) {
  return String(text).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

// Looks the club up through Supabase's public REST endpoint with the project's
// publishable (anon) key — the same read the app's club discovery does, and the
// clubs table is world-readable by design (name, member count and city are
// public; only the roster is members-only). Only these five columns are
// requested. Any failure (no config, timeout, non-200, no row) returns null and
// the page falls back to the generic copy, so a Supabase outage can never turn a
// share link into an error page.
async function lookupClub(env, clubId) {
  if (!env || !env.SUPABASE_URL || !env.SUPABASE_ANON_KEY) return null;
  try {
    const api = `${env.SUPABASE_URL}/rest/v1/clubs?id=eq.${clubId}&select=name,member_count,city,cover_url,is_private&limit=1`;
    const res = await fetch(api, {
      headers: { apikey: env.SUPABASE_ANON_KEY, accept: "application/json" },
      signal: AbortSignal.timeout(2500),
      cf: { cacheTtl: 300, cacheEverything: true },
    });
    if (!res.ok) return null;
    const rows = await res.json();
    const row = Array.isArray(rows) ? rows[0] : null;
    if (!row || typeof row.name !== "string" || !row.name.trim()) return null;
    // The cover is only ever echoed into og:image, and only when it lives in
    // this project's public storage bucket path — never an arbitrary URL.
    // Private clubs keep the branded image: their cover is not for strangers.
    const storagePrefix = `${env.SUPABASE_URL}/storage/v1/object/public/`;
    const cover = typeof row.cover_url === "string" && row.cover_url.startsWith(storagePrefix) && row.is_private === false ? row.cover_url : null;
    return {
      name: row.name.trim().slice(0, 80),
      members: Number.isFinite(row.member_count) ? row.member_count : null,
      city: typeof row.city === "string" && row.city.trim() ? row.city.trim().slice(0, 60) : null,
      cover,
    };
  } catch {
    return null;
  }
}

function clubResponse(request, url, clubId, eventId, club) {
  const lang = pickLang(request, url);
  const c = CLUB_COPY[lang];
  let [title, blurb] = eventId ? c.event : c.club;
  let ogImage = `${SITE}/assets/og.jpg`;
  let hasCover = false;
  if (club && !eventId) {
    const p = CLUB_PREVIEW[lang];
    title = esc(p.title.replace("{name}", () => club.name));
    const parts = [];
    if (club.members !== null) parts.push((club.members === 1 ? p.members[0] : p.members[1]).replace("{n}", club.members));
    if (club.city) parts.push(esc(club.city));
    blurb = parts.length ? parts.join(" · ") : blurb;
    if (club.cover) { ogImage = esc(club.cover); hasCover = true; }
  }
  // Both ids are validated UUIDs, so the deep link is built from known-safe text.
  const deepLink = eventId
    ? `routerush://club/${clubId}/event/${eventId}`
    : `routerush://club/${clubId}`;
  const canonical = `${SITE}${url.pathname}`;
  const langLinks = Object.keys(CLUB_COPY)
    .map((l) => (l === lang ? `<span aria-current="true">${LANG_NAMES[l]}</span>` : `<a href="${url.pathname}?lang=${l}" hreflang="${l}">${LANG_NAMES[l]}</a>`))
    .join("");
  const html = `<!doctype html>
<html lang="${lang}">
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
<meta property="og:url" content="${canonical}">
<meta property="og:image" content="${ogImage}">${hasCover ? "" : `
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">`}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${title}">
<meta name="twitter:description" content="${blurb}">
<meta name="twitter:image" content="${ogImage}">
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
  .langs{margin-top:26px;font-size:13px;color:rgba(255,255,255,.38);display:flex;flex-wrap:wrap;justify-content:center;gap:4px 16px}
  .langs a{color:rgba(255,255,255,.55);text-decoration:none}
  .langs span{color:#fff}
  .foot{margin-top:12px;margin-bottom:0;font-size:13px;color:rgba(255,255,255,.38)}
  .foot a{color:inherit}
</style>
</head>
<body>
  <div class="card">
    <div class="mark"><a href="${SITE}/">RouteRush</a></div>
    <h1>${title}</h1>
    <p>${blurb}</p>
    <a class="btn primary" href="${deepLink}">${c.open}</a>
    <a class="btn ghost" href="${APP_STORE_URL}">${c.get}</a>
    <nav class="langs" aria-label="Language">${langLinks}</nav>
    <p class="foot"><a href="${SITE}/">routerushapp.com</a></p>
  </div>
</body>
</html>`;
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=300",
      vary: "Accept-Language",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
    },
  });
}
const APP_STORE_URL = "https://apps.apple.com/app/id6783352912";
const SITE = "https://routerushapp.com";
const AASA = {
  applinks: {
    details: [
      { appIDs: ["3M483H3X58.FethiOmur.RouteRushApp"], components: [{ "/": "/club/*", comment: "Club and club event share links open the app" }] },
    ],
  },
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Universal links. Served here rather than from the Pages origin so the
    // Content-Type is a guaranteed application/json (an extensionless static
    // file is served as octet-stream), with no redirect and no Jekyll in the
    // way. Only /club/* opens the app; /post/ and /u/ stay web-only for now.
    if (path === "/.well-known/apple-app-site-association") {
      return new Response(JSON.stringify(AASA), {
        status: 200,
        headers: { "content-type": "application/json", "cache-control": "public, max-age=3600", "x-content-type-options": "nosniff" },
      });
    }

    if (path.startsWith("/club/")) {
      // /club/<uuid> or /club/<uuid>/event/<uuid>; a trailing slash is allowed.
      const seg = path.split("/").filter(Boolean); // ["club", id, "event"?, id?]
      const okClub = seg.length >= 2 && UUID.test(seg[1]);
      if (okClub && seg.length === 2) {
        const id = seg[1].toLowerCase();
        return clubResponse(request, url, id, null, await lookupClub(env, id));
      }
      if (okClub && seg.length === 4 && seg[2] === "event" && UUID.test(seg[3])) {
        return clubResponse(request, url, seg[1].toLowerCase(), seg[3].toLowerCase(), null);
      }
      return fetch(request);
    }

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
