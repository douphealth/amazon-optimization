// Cloudflare Worker portfolio-indexnow-key as it was before 2026-11-26 (rollback copy; see docs/indexnow.md).
// The IndexNow key values are removed; the originals are in the owner's private backup bundle.
export default { async fetch(request) { return new Response('<indexnow-key-redacted>', { headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control':'public, max-age=86400' } }); } };
