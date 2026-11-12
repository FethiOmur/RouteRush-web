// Fallback for the routerush-site Worker (wrangler.site.jsonc).
//
// Static assets are matched first and never reach this code, so file requests
// stay free. It only runs when no file matches the exact path, which with
// html_handling "none" means directory URLs ("/", "/tr/") and misses. It keeps
// the URL behaviour GitHub Pages had:
//   /dir/  -> /dir/index.html
//   /dir   -> 301 /dir/   when /dir/index.html exists
//   /page  -> 301 /page.html  when that file exists (/index -> 301 /)
// Everything else gets the site's 404.html with a 404 status.
//
// Video is the one exception to "files never reach this code": static assets
// answer a Range request with the whole file and a 200, and Safari will not
// play an <video> without 206 responses. wrangler.site.jsonc routes *.mp4
// here first (run_worker_first) so serveRange can answer with 206.

// Only these request headers are forwarded to env.ASSETS.fetch. The incoming
// Request is never reused as the init of an asset fetch (its headers and body
// would leak into every lookup); each asset request is built fresh from the
// URL, the method and, where the response goes back to the client, the
// conditional headers.
const CONDITIONAL = ["if-none-match", "if-modified-since"];

function assetRequest(request, assetUrl, conditional) {
  const headers = new Headers();
  if (conditional) {
    for (const name of CONDITIONAL) {
      const v = request.headers.get(name);
      if (v !== null) headers.set(name, v);
    }
  }
  return new Request(assetUrl, { method: request.method, headers });
}

// 404.html with a 404 status. Fetched without conditional headers so it is
// never a 304, and stripped of validators so a cached 404 cannot be
// revalidated into a different page.
async function notFoundResponse(request, env, origin) {
  const notFound = await env.ASSETS.fetch(
    new Request(new URL("/404.html", origin), { method: request.method === "HEAD" ? "HEAD" : "GET" })
  );
  if (!notFound.ok) return new Response(request.method === "HEAD" ? null : "Not found", { status: 404 });
  const headers = new Headers(notFound.headers);
  headers.delete("etag");
  headers.delete("last-modified");
  return new Response(notFound.body, { status: 404, headers });
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", { status: 405, headers: { allow: "GET, HEAD" } });
    }
    const url = new URL(request.url);
    // Collapse leading slashes so "//evil.com/x" cannot turn into another
    // host, and only ever build URLs by setting pathname on our own origin.
    const path = url.pathname.replace(/^\/+/, "/");
    const sameOrigin = (p, search = "") => {
      const u = new URL(url.origin);
      u.pathname = p;
      u.search = search;
      return u;
    };

    if (path.endsWith(".mp4")) return serveRange(request, env, sameOrigin(path));

    // A 304 is a hit: the asset exists and the client's copy is current.
    // `conditional` is true only for the lookup whose response is returned to
    // the client; existence probes for redirects send no validators.
    const tryAsset = async (p, conditional = false) => {
      const res = await env.ASSETS.fetch(assetRequest(request, sameOrigin(p), conditional));
      return res.ok || res.status === 304 ? res : null;
    };

    if (path.endsWith("/")) {
      const res = await tryAsset(path + "index.html", true);
      if (res) return res;
    } else if (!path.split("/").pop().includes(".")) {
      if (await tryAsset(path + "/index.html")) {
        return Response.redirect(sameOrigin(path + "/", url.search), 301);
      }
      // One URL per page: the extensionless form redirects to the .html
      // file the sitemap and canonicals name, and "/index" to its directory.
      const name = path.split("/").pop();
      if (name === "index") return Response.redirect(sameOrigin(path.slice(0, -5), url.search), 301);
      if (name !== "404" && (await tryAsset(path + ".html"))) {
        return Response.redirect(sameOrigin(path + ".html", url.search), 301);
      }
    }

    return notFoundResponse(request, env, url.origin);
  },
};

// True when an If-None-Match header (a list of entity tags, or "*") matches
// the asset's etag. Weak comparison, as RFC 9110 requires for GET/HEAD.
function etagMatches(ifNoneMatch, etag) {
  if (!ifNoneMatch || !etag) return false;
  const strip = (t) => t.trim().replace(/^W\//, "");
  const want = strip(etag);
  return ifNoneMatch.split(",").some((t) => t.trim() === "*" || strip(t) === want);
}

async function serveRange(request, env, assetUrl) {
  // Always a plain GET without validators: this function answers the
  // conditional and range logic itself from the full asset.
  const res = await env.ASSETS.fetch(new Request(assetUrl, { method: "GET" }));
  if (!res.ok) return notFoundResponse(request, env, assetUrl);
  const headers = new Headers(res.headers);
  headers.set("accept-ranges", "bytes");
  const isHead = request.method === "HEAD";

  if (etagMatches(request.headers.get("if-none-match"), res.headers.get("etag"))) {
    headers.delete("content-length");
    return new Response(null, { status: 304, headers });
  }

  const range = request.headers.get("range");
  const m = range ? /^bytes=(\d*)-(\d*)$/.exec(range.trim()) : null;
  // No Range, or one that does not parse (wrong unit, several ranges, "abc",
  // "bytes=-"): the full 200 response, which RFC 9110 says to send when the
  // Range header is not understood.
  if (!m || (m[1] === "" && m[2] === "")) {
    if (!isHead) return new Response(res.body, { status: 200, headers });
    if (!headers.has("content-length")) {
      headers.set("content-length", String((await res.arrayBuffer()).byteLength));
    }
    return new Response(null, { status: 200, headers });
  }

  const buf = await res.arrayBuffer();
  const size = buf.byteLength;
  let start, end;
  if (m[1] !== "") {
    start = Number(m[1]);
    end = m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1);
    // "bytes=5-2" is syntactically invalid: ignore the header.
    if (m[2] !== "" && Number(m[2]) < start) {
      headers.set("content-length", String(size));
      return new Response(isHead ? null : buf, { status: 200, headers });
    }
  } else {
    start = Math.max(size - Number(m[2]), 0); // suffix range: last N bytes
    end = size - 1;
    if (Number(m[2]) === 0) start = size; // "bytes=-0" selects nothing
  }
  // Parsed but unsatisfiable: 416.
  if (start >= size) {
    headers.set("content-range", `bytes */${size}`);
    headers.delete("content-length");
    return new Response(null, { status: 416, headers });
  }
  headers.set("content-range", `bytes ${start}-${end}/${size}`);
  headers.set("content-length", String(end - start + 1));
  return new Response(isHead ? null : buf.slice(start, end + 1), { status: 206, headers });
}
