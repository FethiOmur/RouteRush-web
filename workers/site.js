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

export default {
  async fetch(request, env) {
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

    const tryAsset = async (p) => {
      const res = await env.ASSETS.fetch(sameOrigin(p), request);
      return res.ok ? res : null;
    };

    if (path.endsWith("/")) {
      const res = await tryAsset(path + "index.html");
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

    const notFound = await env.ASSETS.fetch(sameOrigin("/404.html"), request);
    return new Response(notFound.body, { status: 404, headers: notFound.headers });
  },
};

async function serveRange(request, env, assetUrl) {
  const res = await env.ASSETS.fetch(assetUrl);
  if (!res.ok) {
    const notFound = await env.ASSETS.fetch(new URL("/404.html", assetUrl));
    return new Response(notFound.body, { status: 404, headers: notFound.headers });
  }
  const headers = new Headers(res.headers);
  headers.set("accept-ranges", "bytes");
  const range = request.headers.get("range");
  const isHead = request.method === "HEAD";
  if (!range) return new Response(isHead ? null : res.body, { status: 200, headers });

  const buf = await res.arrayBuffer();
  const size = buf.byteLength;
  const m = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
  let start, end;
  if (m && m[1] !== "") {
    start = Number(m[1]);
    end = m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1);
  } else if (m && m[2] !== "") {
    start = Math.max(size - Number(m[2]), 0); // suffix range: last N bytes
    end = size - 1;
  }
  if (start === undefined || start > end || start >= size) {
    headers.set("content-range", `bytes */${size}`);
    headers.delete("content-length");
    return new Response(null, { status: 416, headers });
  }
  headers.set("content-range", `bytes ${start}-${end}/${size}`);
  headers.set("content-length", String(end - start + 1));
  return new Response(isHead ? null : buf.slice(start, end + 1), { status: 206, headers });
}
