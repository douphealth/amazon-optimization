// Email-code front door for the dashboard (a Cloudflare Worker, deployed by infra/deploy_gateway.py).
//
// Cloudflare Access sits in front of this Worker's address and asks for an email address, then
// emails a one-time code. This Worker checks Access's signed sign-in token itself as well (the same
// check the dashboard uses, functions/_middleware.js, uploaded alongside as _middleware.mjs), and
// only then fetches the requested file from the dashboard, signing in to it with the dashboard
// password kept as a Worker secret. It only reads: GET and HEAD.
//
// Settings (Worker variables): ACCESS_TEAM_DOMAIN, ACCESS_AUD, ORIGIN (the dashboard's address)
// and the secret DASHBOARD_PASSWORD. Missing settings lock the door rather than open it.

import { accessIdentity } from "./_middleware.mjs";

const DROP = ["WWW-Authenticate", "Set-Cookie", "CDN-Cache-Control", "Cloudflare-CDN-Cache-Control", "Surrogate-Control", "Expires"];

function text(status, body) {
  return new Response(body, { status, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
}

export default {
  async fetch(request, env) {
    if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD || !env.ORIGIN || !env.DASHBOARD_PASSWORD) {
      return text(503, "This dashboard is locked: its sign-in is not configured.");
    }
    let identity = null;
    try { identity = await accessIdentity(request, env); } catch { identity = null; }
    if (!identity) return text(403, "Sign in through the email code page to see the dashboard.");
    if (request.method !== "GET" && request.method !== "HEAD") return text(405, "This dashboard is read-only.");

    const url = new URL(request.url);
    const origin = new URL(env.ORIGIN);
    const target = new URL(url.pathname + url.search, origin);
    const upstream = await fetch(target, {
      method: request.method,
      headers: { Authorization: "Basic " + btoa("gateway:" + env.DASHBOARD_PASSWORD), Accept: request.headers.get("Accept") || "*/*" },
      redirect: "manual",
    });
    const out = new Response(upstream.body, upstream);
    for (const h of DROP) out.headers.delete(h);
    out.headers.set("Cache-Control", "private, no-store");
    out.headers.set("X-Robots-Tag", "noindex, nofollow");
    const location = out.headers.get("Location");
    if (location) {  // keep redirects on this address, never send the browser to the dashboard's own host
      const next = new URL(location, target);
      if (next.host === origin.host) out.headers.set("Location", next.pathname + next.search + next.hash);
    }
    if (upstream.status === 401) return text(502, "The dashboard refused the gateway's password; update the DASHBOARD_PASSWORD secret.");
    return out;
  },
};
