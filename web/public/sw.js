const CACHE_NAME = "stock-ai-shell-v1";
const SHELL = ["/", "/today", "/manifest.webmanifest", "/stock-ai-mark.svg", .../* BUILD_ASSETS */ []];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.pathname.startsWith("/api/")) {
    return;
  }
  // Hashed build assets are immutable, and an older open page may still need
  // its own chunk after deployment has removed that chunk from the server.
  const immutableAsset = url.origin === self.location.origin
    && /^\/assets\/.+-[A-Za-z0-9_-]{8,}\.(js|css)$/.test(url.pathname);
  if (immutableAsset) {
    event.respondWith(caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(request, { ignoreVary: true });
      if (cached) return cached;
      const response = await fetch(request);
      const type = response.headers.get("content-type") || "";
      const isAsset = url.pathname.endsWith(".css") ? /^text\/css(?:;|$)/i.test(type)
        : /^(?:text|application)\/(?:x-)?javascript(?:;|$)/i.test(type);
      if (response.ok && isAsset) {
        try { await cache.put(request, response.clone()); } catch { /* Cache failure must not block the live file. */ }
      }
      return response;
    }));
    return;
  }
  event.respondWith(
    fetch(request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        return response;
      })
      .catch(() => caches.match(request, { ignoreVary: url.origin === self.location.origin && url.pathname.startsWith("/assets/") }).then((cached) => cached || caches.match("/"))),
  );
});
