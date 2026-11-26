// Cloudflare Worker `portfolio-indexnow-key`: serves the IndexNow key file for every site routed to it.
//
// Deployed to the account on 2026-11-26 (with the real keys in KEYS).
//
// Why this version exists: IndexNow requires https://<host>/<key>.txt to contain exactly <key>.
// The deployed version (checked 2026-11-26) returns one hard-coded key for every route, while most
// sites route a file named after a second key to it. On those sites the file name and its content
// disagree, so search engines reject every submission.
//
// This version answers with the key named in the URL, for the keys listed in KEYS. Put every key the
// portfolio uses in KEYS before deploying (they are the 32-character names in the Worker's routes).
// Do not commit real keys to a public repository.
//
// Deploy: ES module, main module `worker.js`. Routes stay as they are. To cover a site that has no
// route yet (affiliatemarketingforsuccess.com, www.outdoormisting.com), add `<host>/<key>.txt`.
// Verify: `curl https://<host>/<key>.txt` must print the key and nothing else.
const KEYS = new Set(['REPLACE_WITH_FIRST_KEY', 'REPLACE_WITH_SECOND_KEY']);

export default {
  async fetch(request) {
    const match = new URL(request.url).pathname.match(/^\/([0-9a-f]{32})\.txt$/);
    if (!match || !KEYS.has(match[1])) {
      return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain; charset=utf-8' } });
    }
    return new Response(match[1], {
      headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'public, max-age=3600' },
    });
  },
};
