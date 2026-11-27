// Sign-in for the whole dashboard (pages, data.json, downloads), run by Cloudflare Pages in front
// of every request. Two modes, chosen by the Pages project's variables:
//
//   Email code (Cloudflare Access): ACCESS_TEAM_DOMAIN and ACCESS_AUD are set. Cloudflare Access
//   asks for an email address and sends a one-time code; this code then checks the signed token
//   Access attaches to every request (signature, audience, issuer, expiry) as a second lock.
//   Set up by infra/setup_access.py.
//
//   Password: only DASHBOARD_PASSWORD is set (a Pages secret). HTTP Basic auth, any user name.
//
// With neither, the dashboard stays locked rather than open. Nothing secret is in this file.

const REALM = 'Basic realm="Commission Engine", charset="UTF-8"';
const CERT_TTL_MS = 60 * 60 * 1000;
let certCache = { url: "", at: 0, keys: [] };

export async function onRequest({ request, env, next }) {
  const pass = async () => {
    const response = await next();
    const out = new Response(response.body, response);
    out.headers.set("Cache-Control", "private, no-store");
    return out;
  };
  if (env.ACCESS_TEAM_DOMAIN && env.ACCESS_AUD) {
    const identity = await accessIdentity(request, env);
    return identity ? pass() : plain(403, "Sign in through the email code page (Cloudflare Access) to see the dashboard.");
  }
  if (env.DASHBOARD_PASSWORD) {
    return (await passwordOk(request, env.DASHBOARD_PASSWORD)) ? pass() : challenge();
  }
  return plain(503, "This dashboard is locked: no sign-in is configured for it.");
}

function plain(status, text, extra = {}) {
  return new Response(text, { status, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", ...extra } });
}
const challenge = () => plain(401, "Sign in to see the dashboard.", { "WWW-Authenticate": REALM });

// ---------- email code: verify the Cloudflare Access token ----------

function teamOrigin(domain) {
  const host = String(domain).replace(/^https?:\/\//, "").replace(/\/+$/, "");
  return `https://${host}`;
}

function accessToken(request) {
  const header = request.headers.get("Cf-Access-Jwt-Assertion");
  if (header) return header;
  const cookie = request.headers.get("Cookie") || "";
  const m = cookie.match(/(?:^|;\s*)CF_Authorization=([^;]+)/);
  return m ? m[1] : "";
}

function b64urlBytes(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  return Uint8Array.from(atob(s), c => c.charCodeAt(0));
}
const b64urlJson = s => JSON.parse(new TextDecoder().decode(b64urlBytes(s)));

async function certs(origin, fetchImpl, force = false) {
  const url = `${origin}/cdn-cgi/access/certs`;
  if (!force && certCache.url === url && Date.now() - certCache.at < CERT_TTL_MS && certCache.keys.length) return certCache.keys;
  const res = await fetchImpl(url);
  if (!res.ok) return [];
  const body = await res.json();
  certCache = { url, at: Date.now(), keys: body.keys || [] };
  return certCache.keys;
}

// Returns the verified claims, or null. Exported for tests.
export async function accessIdentity(request, env, fetchImpl = fetch, now = Date.now()) {
  const token = accessToken(request);
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  let header, claims;
  try { header = b64urlJson(parts[0]); claims = b64urlJson(parts[1]); } catch { return null; }
  if (header.alg !== "RS256" || !header.kid) return null;
  const origin = teamOrigin(env.ACCESS_TEAM_DOMAIN);
  const audiences = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  const seconds = Math.floor(now / 1000);
  if (claims.iss !== origin || !audiences.includes(env.ACCESS_AUD)) return null;
  if (typeof claims.exp !== "number" || claims.exp < seconds) return null;
  if (typeof claims.nbf === "number" && claims.nbf > seconds + 60) return null;
  let jwk = (await certs(origin, fetchImpl)).find(k => k.kid === header.kid);
  if (!jwk) jwk = (await certs(origin, fetchImpl, true)).find(k => k.kid === header.kid);  // keys rotate
  if (!jwk) return null;
  try {
    const key = await crypto.subtle.importKey("jwk", { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64urlBytes(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
    return ok ? claims : null;
  } catch {
    return null;
  }
}

// ---------- password ----------

async function passwordOk(request, expected) {
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Basic ")) return false;
  let decoded = "";
  try { decoded = new TextDecoder().decode(Uint8Array.from(atob(header.slice(6)), c => c.charCodeAt(0))); } catch { return false; }
  if (!decoded.includes(":")) return false;
  return equal(decoded.slice(decoded.indexOf(":") + 1), expected);
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
