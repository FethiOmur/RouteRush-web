// Fallback for the routerush-site Worker (wrangler.site.jsonc).
//
// Static assets are matched first and never reach this code, so file requests
// stay free. It only runs when no file matches the exact path, which with
// html_handling "none" means directory URLs ("/", "/tr/") and misses. It keeps
// the URL behaviour GitHub Pages had:
//   /dir/  -> /dir/index.html
//   /dir   -> 301 /dir/   when /dir/index.html exists
//   /page  -> /page.html  when that file exists
// Everything else gets the site's 404.html with a 404 status.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    const tryAsset = async (p) => {
      const res = await env.ASSETS.fetch(new URL(p, url), request);
      return res.ok ? res : null;
    };

    if (path.endsWith("/")) {
      const res = await tryAsset(path + "index.html");
      if (res) return res;
    } else if (!path.split("/").pop().includes(".")) {
      if (await tryAsset(path + "/index.html")) {
        return Response.redirect(new URL(path + "/" + url.search, url), 301);
      }
      const res = await tryAsset(path + ".html");
      if (res) return res;
    }

    const notFound = await env.ASSETS.fetch(new URL("/404.html", url), request);
    return new Response(notFound.body, { status: 404, headers: notFound.headers });
  },
};
