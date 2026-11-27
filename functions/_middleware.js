// Sign-in for the whole dashboard (pages, data.json, downloads), run by Cloudflare Pages in front
// of every request. Two modes, chosen by the Pages project's variables:
//
//   Email code (Cloudflare Access): ACCESS_TEAM_DOMAIN and ACCESS_AUD are set. Cloudflare Access
//   asks for an email address and sends a one-time code; this code then checks the signed token
//   Access attaches to every request (signature, audience, issuer, expiry) as a second lock.
//   Set up by infra/setup_access.py.
//
//   Password: only DASHBOARD_PASSWORD is set (a Pages secret). HTTP Basic auth, any user name.
//   With GATEWAY_URL also set (the email-code front door, infra/gateway/worker.js), people are never
//   shown a password box: a visit without a password is sent to the email-code sign-in instead, and
//   only the gateway, which holds the password, reads the dashboard here.
//
// With neither, the dashboard stays locked rather than open. Nothing secret is in this file.
// Never call passThroughOnException() here: an error must end in a refusal, not in the dashboard.

const REALM = 'Basic realm="Commission Engine", charset="UTF-8"';
const CERT_TTL_MS = 60 * 60 * 1000;
const FORCED_REFRESH_MS = 60 * 1000;  // an unknown key id may refetch the keys at most once a minute
const CERT_TIMEOUT_MS = 5000;
const NO_STORE = ["CDN-Cache-Control", "Cloudflare-CDN-Cache-Control", "Surrogate-Control", "Expires"];
let certCache = { url: "", at: 0, keys: [], forcedAt: 0 };

export async function onRequest({ request, env, next }) {
  const pass = async () => {
    const response = await next();
    const out = new Response(response.body, response);
    out.headers.set("Cache-Control", "private, no-store");
    for (const h of NO_STORE) out.headers.delete(h);
    return out;
  };
  if (env.ACCESS_TEAM_DOMAIN || env.ACCESS_AUD) {
    // Half a configuration must not quietly fall back to the password.
    if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) return plain(503, "Sign-in is misconfigured: ACCESS_TEAM_DOMAIN and ACCESS_AUD must both be set.");
    let identity = null;
    try { identity = await accessIdentity(request, env); } catch { identity = null; }
    return identity ? pass() : plain(403, "Sign in through the email code page (Cloudflare Access) to see the dashboard.");
  }
  if (env.DASHBOARD_PASSWORD) {
    if (await passwordOk(request, env.DASHBOARD_PASSWORD)) return pass();
    const gateway = gatewayOrigin(env.GATEWAY_URL);
    if (!gateway) return challenge();
    // A wrong password (the gateway's, once the secret changes) gets a refusal without a password
    // box; a visit with no password is sent to the email-code page, at the same path.
    if (request.headers.has("Authorization")) return plain(401, "Sign in through the email code page.");
    if (request.method !== "GET" && request.method !== "HEAD") return plain(405, "This dashboard is read-only.");
    const url = new URL(request.url);
    return new Response(null, { status: 302, headers: { Location: gateway + url.pathname + url.search, "Cache-Control": "no-store" } });
  }
  return plain(503, "This dashboard is locked: no sign-in is configured for it.");
}

function plain(status, text, extra = {}) {
  return new Response(text, { status, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store", ...extra } });
}
const challenge = () => plain(401, "Sign in to see the dashboard.", { "WWW-Authenticate": REALM });

// The email-code address, as an https origin only, so the redirect can never point anywhere else
// (the path is appended to the origin as text: a path like //other.example stays on this origin).
function gatewayOrigin(value) {
  if (!value) return "";
  try {
    const u = new URL(value);
    return u.protocol === "https:" && !u.username && !u.password ? u.origin : "";
  } catch {
    return "";
  }
}

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

const validKey = k => k && typeof k === "object" && typeof k.kid === "string" && k.kty === "RSA" && typeof k.n === "string" && typeof k.e === "string";

// The team's public keys, cached for an hour. Failures return what is cached for this team (or
// nothing); a bad answer never replaces good keys.
async function certs(origin, fetchImpl, force = false) {
  const url = `${origin}/cdn-cgi/access/certs`;
  const cached = certCache.url === url ? certCache.keys : [];
  const fresh = certCache.url === url && Date.now() - certCache.at < CERT_TTL_MS && cached.length;
  if (fresh && !force) return cached;
  if (force && certCache.url === url && Date.now() - certCache.forcedAt < FORCED_REFRESH_MS) return cached;
  if (force && certCache.url === url) certCache.forcedAt = Date.now();
  try {
    const res = await fetchImpl(url, { signal: AbortSignal.timeout(CERT_TIMEOUT_MS) });
    if (!res.ok) return cached;
    const body = await res.json();
    const keys = Array.isArray(body && body.keys) ? body.keys.filter(validKey) : [];
    if (!keys.length) return cached;
    certCache = { url, at: Date.now(), keys, forcedAt: certCache.url === url ? certCache.forcedAt : 0 };
    return keys;
  } catch {
    return cached;
  }
}

// Returns the verified claims, or null. Exported for tests.
export async function accessIdentity(request, env, fetchImpl = fetch, now = Date.now()) {
  const token = accessToken(request);
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  let header, claims;
  try { header = b64urlJson(parts[0]); claims = b64urlJson(parts[1]); } catch { return null; }
  const isObject = x => x !== null && typeof x === "object" && !Array.isArray(x);
  if (!isObject(header) || !isObject(claims)) return null;
  if (header.alg !== "RS256" || typeof header.kid !== "string" || !header.kid) return null;
  const origin = teamOrigin(env.ACCESS_TEAM_DOMAIN);
  const audiences = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  const seconds = Math.floor(now / 1000);
  if (claims.iss !== origin || !audiences.includes(env.ACCESS_AUD)) return null;
  if (typeof claims.exp !== "number" || claims.exp <= seconds) return null;
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
