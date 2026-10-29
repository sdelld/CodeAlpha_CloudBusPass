/* Service worker for the rider app: keeps the app shell available offline so a pass can always be shown.
   API responses are never cached here — the app keeps its own small pass cache in localStorage. */
const CACHE = "cloudbus-shell-v1";
const SHELL = ["/app", "/static/css/app.css", "/static/js/i18n.js", "/static/js/core.js", "/static/js/rider.js",
  "/static/vendor/qrcode.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  if (e.request.mode === "navigate") {
    // Network first so updates arrive; fall back to the cached shell when offline.
    e.respondWith(fetch(e.request).then((r) => { caches.open(CACHE).then((c) => c.put("/app", r.clone())); return r; })
      .catch(() => caches.match("/app")));
    return;
  }
  if (SHELL.includes(url.pathname)) {
    e.respondWith(caches.match(e.request).then((cached) => {
      const fresh = fetch(e.request).then((r) => { caches.open(CACHE).then((c) => c.put(e.request, r.clone())); return r; });
      return cached || fresh;
    }));
  }
});
