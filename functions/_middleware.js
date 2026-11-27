// Password protection for the whole dashboard (pages, data.json, downloads), run by Cloudflare
// Pages in front of every request. The password is the DASHBOARD_PASSWORD secret in the Pages
// project (Settings > Variables and Secrets); it is never in this repository. Any user name works.
// Without the secret the dashboard stays locked rather than open.

const REALM = 'Basic realm="Commission Engine", charset="UTF-8"';

export async function onRequest({ request, env, next }) {
  const expected = env.DASHBOARD_PASSWORD;
  if (!expected) {
    return new Response("This dashboard is locked: set DASHBOARD_PASSWORD in the Cloudflare Pages project.", {
      status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }
  const header = request.headers.get("Authorization") || "";
  if (header.startsWith("Basic ")) {
    let decoded = "";
    try { decoded = new TextDecoder().decode(Uint8Array.from(atob(header.slice(6)), c => c.charCodeAt(0))); } catch { decoded = ""; }
    const password = decoded.slice(decoded.indexOf(":") + 1);
    if (decoded.includes(":") && await equal(password, expected)) {
      const response = await next();
      const out = new Response(response.body, response);
      out.headers.set("Cache-Control", "private, no-store");
      return out;
    }
  }
  return new Response("Sign in to see the dashboard.", {
    status: 401, headers: { "WWW-Authenticate": REALM, "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
  });
}

// Compare SHA-256 digests byte by byte, so the time taken does not depend on where the inputs differ.
async function equal(a, b) {
  const enc = new TextEncoder();
  const [x, y] = await Promise.all([crypto.subtle.digest("SHA-256", enc.encode(a)), crypto.subtle.digest("SHA-256", enc.encode(b))]);
  const u = new Uint8Array(x), v = new Uint8Array(y);
  let diff = 0;
  for (let i = 0; i < u.length; i++) diff |= u[i] ^ v[i];
  return diff === 0;
}
