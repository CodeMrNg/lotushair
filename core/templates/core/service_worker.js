const CACHE_NAME = "lotus-hair-static-v1";
const STATIC_ASSETS = [
  "/static/core/styles.css?v=2.5",
  "/static/core/img/logo.jpeg",
  "/static/core/img/pwa-icon-192.png",
  "/static/core/img/pwa-icon-512.png",
  "/static/core/manifest.webmanifest"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches
      .keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
          return response;
        });
      })
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(
          "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Lotus Hair hors ligne</title><body style=\"font-family:system-ui;padding:24px;background:#FAF9F6;color:#3E1B25\"><h1>Lotus Hair</h1><p>Connexion indisponible. Reessayez lorsque le reseau est revenu.</p></body></html>",
          { headers: { "Content-Type": "text/html; charset=utf-8" } }
        )
      )
    );
  }
});
