// Checks the email-code gateway (worker.js) without Cloudflare: a locally made signing key stands in
// for the Access team's, and a fake fetch stands in for the dashboard.  Run: node infra/gateway/worker.test.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gateway-"));
fs.copyFileSync(path.join(here, "..", "..", "functions", "_middleware.js"), path.join(dir, "_middleware.mjs"));
fs.copyFileSync(path.join(here, "worker.js"), path.join(dir, "worker.mjs"));
const gateway = (await import(pathToFileURL(path.join(dir, "worker.mjs")).href)).default;

const { subtle } = globalThis.crypto;
const pair = await subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const other = await subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await subtle.exportKey("jwk", pair.publicKey)), kid: "k1" };
const b64u = b => Buffer.from(b).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
async function token(claims, key = pair.privateKey, alg = "RS256") {
  const head = b64u(JSON.stringify({ alg, kid: "k1" })), body = b64u(JSON.stringify(claims));
  const sig = await subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64u(new Uint8Array(sig))}`;
}

const now = Math.floor(Date.now() / 1000);
const env = { ACCESS_TEAM_DOMAIN: "team.cloudflareaccess.com", ACCESS_AUD: "aud1", ORIGIN: "https://dash.pages.dev", DASHBOARD_PASSWORD: "pw" };
const claims = { iss: "https://team.cloudflareaccess.com", aud: ["aud1"], exp: now + 600, email: "owner@example.com" };
const good = await token(claims);

const upstream = [];
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  if (url === "https://team.cloudflareaccess.com/cdn-cgi/access/certs") return new Response(JSON.stringify({ keys: [jwk] }));
  upstream.push({ url, method: init.method, auth: init.headers?.Authorization, redirect: init.redirect });
  if (url.includes("/old")) return new Response(null, { status: 308, headers: { Location: "https://dash.pages.dev/new?x=1" } });
  if (url.includes("/away")) return new Response(null, { status: 302, headers: { Location: "https://elsewhere.example/" } });
  if (url.includes("/locked")) return new Response("no", { status: 401, headers: { "WWW-Authenticate": "Basic" } });
  return new Response("CONTENT " + new URL(url).pathname + new URL(url).search, {
    headers: { "Set-Cookie": "a=b", "WWW-Authenticate": "x", "Cache-Control": "public, max-age=999", "CDN-Cache-Control": "max-age=999", Expires: "x" },
  });
};
const call = (p, headers = {}, method = "GET", e = env) => gateway.fetch(new Request("https://gateway.example.workers.dev" + p, { method, headers }), e);
const signed = { "Cf-Access-Jwt-Assertion": good };

// Signed in: the file comes from the dashboard, fetched with the password, never cached or indexed.
let r = await call("/data.json?v=1", signed);
assert.equal(r.status, 200);
assert.equal(await r.text(), "CONTENT /data.json?v=1");
assert.equal(upstream.at(-1).url, "https://dash.pages.dev/data.json?v=1");
assert.equal(upstream.at(-1).auth, "Basic " + btoa("gateway:pw"));
assert.equal(upstream.at(-1).redirect, "manual");
assert.equal(r.headers.get("Cache-Control"), "private, no-store");
assert.equal(r.headers.get("X-Robots-Tag"), "noindex, nofollow");
for (const h of ["Set-Cookie", "WWW-Authenticate", "CDN-Cache-Control", "Expires"]) assert.equal(r.headers.get(h), null, h);

// The sign-in cookie works as well as the header.
r = await call("/", { Cookie: `x=1; CF_Authorization=${good}` });
assert.equal(r.status, 200);

// Redirects on the dashboard's host stay on the gateway; others pass through untouched.
r = await call("/old", signed);
assert.equal(r.status, 308);
assert.equal(r.headers.get("Location"), "/new?x=1");
r = await call("/away", signed);
assert.equal(r.headers.get("Location"), "https://elsewhere.example/");

// The dashboard refusing the password is reported, not passed to the browser as a password prompt.
r = await call("/locked", signed);
assert.equal(r.status, 502);
assert.equal(r.headers.get("WWW-Authenticate"), null);

// Refused before the dashboard is ever asked.
const before = upstream.length;
const refusals = [
  ["no sign-in", await call("/data.json"), 403],
  ["malformed token", await call("/data.json", { "Cf-Access-Jwt-Assertion": "a.b.c" }), 403],
  ["signed by another key", await call("/data.json", { "Cf-Access-Jwt-Assertion": await token(claims, other.privateKey) }), 403],
  ["other application", await call("/data.json", { "Cf-Access-Jwt-Assertion": await token({ ...claims, aud: ["aud2"] }) }), 403],
  ["other team", await call("/data.json", { "Cf-Access-Jwt-Assertion": await token({ ...claims, iss: "https://evil.cloudflareaccess.com" }) }), 403],
  ["expired", await call("/data.json", { "Cf-Access-Jwt-Assertion": await token({ ...claims, exp: now - 1 }) }), 403],
  ["alg none", await call("/data.json", { "Cf-Access-Jwt-Assertion": (await token(claims)).replace(/^[^.]+/, b64u(JSON.stringify({ alg: "none", kid: "k1" }))) }), 403],
  ["write method", await call("/data.json", signed, "POST"), 405],
  ["missing password setting", await call("/data.json", signed, "GET", { ...env, DASHBOARD_PASSWORD: "" }), 503],
  ["missing application setting", await call("/data.json", signed, "GET", { ...env, ACCESS_AUD: "" }), 503],
];
for (const [name, res, status] of refusals) assert.equal(res.status, status, name);
assert.equal(upstream.length, before, "a refused request reached the dashboard");

fs.rmSync(dir, { recursive: true, force: true });
console.log(`gateway: ${refusals.length + 6} checks passed`);
