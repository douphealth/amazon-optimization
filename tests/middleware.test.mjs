// Checks the dashboard's own sign-in (functions/_middleware.js) without Cloudflare: password mode,
// email-code (Access) mode with a locally made signing key, the locked default, and the cache headers.
// Run: node tests/middleware.test.mjs   (also run by tests/test_engine.py)
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const source = pathToFileURL(path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "functions", "_middleware.js")).href;
let loads = 0;
const fresh = () => import(`${source}?copy=${++loads}`);  // a new module, so the key cache starts empty

const { subtle } = globalThis.crypto;
const gen = () => subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const pair = await gen(), other = await gen();
const jwk = { ...(await subtle.exportKey("jwk", pair.publicKey)), kid: "k1" };
const b64u = b => Buffer.from(b).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
async function sign(claims, { kid = "k1", alg = "RS256", key = pair.privateKey } = {}) {
  const h = b64u(JSON.stringify({ alg, kid, typ: "JWT" })), p = b64u(JSON.stringify(claims));
  const sig = await subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${h}.${p}`));
  return `${h}.${p}.${b64u(new Uint8Array(sig))}`;
}

const s = Math.floor(Date.now() / 1000);
const good = { iss: "https://team.cloudflareaccess.com", aud: ["aud123"], exp: s + 3600, iat: s, email: "owner@example.com" };
const access = { ACCESS_TEAM_DOMAIN: "team.cloudflareaccess.com", ACCESS_AUD: "aud123" };
const password = { DASHBOARD_PASSWORD: "right-password" };
const req = (headers = {}) => new Request("https://dashboard.example.pages.dev/data.json", { headers });
const basic = text => ({ Authorization: "Basic " + btoa(text) });
const jwt = token => ({ "Cf-Access-Jwt-Assertion": token });
let reached = 0;
const next = async () => { reached++; return new Response("DATA", { headers: { "Cache-Control": "public, max-age=999", "CDN-Cache-Control": "max-age=999", Expires: "Thu, 01 Jan 2099 00:00:00 GMT" } }); };

let certFetches = 0;
const keysServer = async () => { certFetches++; return new Response(JSON.stringify({ keys: [jwk] }), { headers: { "content-type": "application/json" } }); };
globalThis.fetch = keysServer;

let mw = await fresh();
const run = (request, env) => mw.onRequest({ request, env, next });
async function expect(name, request, env, status) {
  const before = reached;
  const r = await run(request, env);
  assert.equal(r.status, status, name);
  if (status === 200) {
    assert.equal(await r.text(), "DATA", name);
    assert.equal(r.headers.get("Cache-Control"), "private, no-store", name + ": cache");
    for (const h of ["CDN-Cache-Control", "Expires"]) assert.equal(r.headers.get(h), null, name + ": " + h);
  } else {
    assert.equal(reached, before, name + ": a refused request reached the dashboard");
    assert.equal(r.headers.get("Cache-Control"), "no-store", name + ": refusal cached");
  }
  return r;
}

// Locked by default.
await expect("nothing configured", req(basic("x:right-password")), {}, 503);

// Password mode: any user name, the exact password, a challenge otherwise.
await expect("right password", req(basic("anyone:right-password")), password, 200);
const challenged = await expect("no credentials", req(), password, 401);
assert.match(challenged.headers.get("WWW-Authenticate"), /^Basic realm=/);
await expect("wrong password", req(basic("anyone:wrong")), password, 401);
await expect("password with a colon", req(basic("u:right-password:extra")), password, 401);
await expect("no colon", req(basic("right-password")), password, 401);
await expect("not base64", req({ Authorization: "Basic %%%" }), password, 401);
await expect("bearer instead of basic", req({ Authorization: "Bearer right-password" }), password, 401);
await expect("colon in the password itself", req(basic("u:a:b")), { DASHBOARD_PASSWORD: "a:b" }, 200);

// Email-code mode: the signed Access token is required, and the password stops working.
const both = { ...access, ...password };
await expect("valid token (header)", req(jwt(await sign(good))), both, 200);
await expect("valid token (cookie)", req({ Cookie: `a=b; CF_Authorization=${await sign(good)}` }), both, 200);
await expect("no token", req(), both, 403);
await expect("password no longer enough", req(basic("x:right-password")), both, 403);
await expect("expired", req(jwt(await sign({ ...good, exp: s - 10 }))), both, 403);
await expect("expires this second", req(jwt(await sign({ ...good, exp: s }))), both, 403);
await expect("not yet valid", req(jwt(await sign({ ...good, nbf: s + 3600 }))), both, 403);
await expect("other application", req(jwt(await sign({ ...good, aud: ["other"] }))), both, 403);
await expect("other team", req(jwt(await sign({ ...good, iss: "https://evil.cloudflareaccess.com" }))), both, 403);
await expect("signed by another key", req(jwt(await sign(good, { key: other.privateKey }))), both, 403);
await expect("unknown key id", req(jwt(await sign(good, { kid: "k9" }))), both, 403);
const [h, , sig] = (await sign(good)).split(".");
await expect("tampered claims", req(jwt(`${h}.${b64u(JSON.stringify({ ...good, email: "x@example.com" }))}.${sig}`)), both, 403);
await expect("alg none", req(jwt(`${b64u(JSON.stringify({ alg: "none", kid: "k1" }))}.${b64u(JSON.stringify(good))}.`)), both, 403);
await expect("alg HS256", req(jwt(await sign(good, { alg: "HS256" }))), both, 403);
await expect("garbage", req(jwt("a.b.c")), both, 403);
await expect("JSON null header", req(jwt(`${b64u("null")}.${b64u("{}")}.AA`)), both, 403);
await expect("JSON null claims", req(jwt(`${b64u(JSON.stringify({ alg: "RS256", kid: "k1" }))}.${b64u("null")}.AA`)), both, 403);

// Half an Access configuration never falls back to the password.
await expect("team without application", req(basic("x:right-password")), { ACCESS_TEAM_DOMAIN: access.ACCESS_TEAM_DOMAIN, ...password }, 503);
await expect("application without team", req(basic("x:right-password")), { ACCESS_AUD: access.ACCESS_AUD, ...password }, 503);

// The team's keys are cached; unknown key ids may force at most one refetch a minute.
mw = await fresh();
certFetches = 0;
await expect("first sign-in fetches keys", req(jwt(await sign(good))), access, 200);
for (let i = 0; i < 20; i++) await expect("unknown kid " + i, req(jwt(await sign(good, { kid: "rnd" + i }))), access, 403);
await expect("cached keys still work", req(jwt(await sign(good))), access, 200);
assert.ok(certFetches <= 2, `keys fetched ${certFetches} times for 1 sign-in + 20 unknown key ids`);

// A broken or unreachable key server refuses rather than lets anyone in.
mw = await fresh();
globalThis.fetch = async () => new Response("<html>oops</html>", { status: 200 });
await expect("keys endpoint answers HTML", req(jwt(await sign(good))), access, 403);
mw = await fresh();
globalThis.fetch = async () => { throw new Error("network down"); };
await expect("keys endpoint unreachable", req(jwt(await sign(good))), access, 403);
mw = await fresh();
globalThis.fetch = async () => new Response(JSON.stringify({ keys: [{ kid: "k1", kty: "EC" }] }));
await expect("keys endpoint answers junk keys", req(jwt(await sign(good))), access, 403);
globalThis.fetch = keysServer;

console.log("middleware: all checks passed");
