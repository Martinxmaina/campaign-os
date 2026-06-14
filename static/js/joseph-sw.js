/* Joseph's principal surface — service worker.
 *
 * Makes /joseph/ installable + offline-resilient for the principal who opens it
 * before every conversation, sometimes on a phone with no signal:
 *   - install: precache a tiny app shell (home + manifest).
 *   - fetch:   cache-first for visited dossier briefs (/joseph/brief/*) so a
 *              brief Joseph has opened once is available offline ("I'm going in"
 *              precaches the brief he's about to walk into); network-first with a
 *              cache fallback for everything else under /joseph/.
 *
 * Scope is /joseph/ (set at registration) so it never intercepts the rest of
 * Campaign OS. Only GETs are cached — never mutate the cache for POSTs.
 */
const CACHE = "joseph-v1";
const APP_SHELL = ["/joseph/?view=mobile", "/static/joseph/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(APP_SHELL).catch(() => null))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Cache-first for visited briefs: an opened dossier is readable offline.
  if (url.pathname.startsWith("/joseph/brief/")) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
            return res;
          }).catch(() => caches.match("/joseph/?view=mobile"))
      )
    );
    return;
  }

  // Network-first with a cache fallback for the rest of the /joseph/ surface.
  if (url.pathname.startsWith("/joseph/")) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match("/joseph/?view=mobile")))
    );
  }
});
