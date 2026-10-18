const CACHE = "skatecue-pwa-v3";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) =>
        cache.addAll(["/icons/icon-192.png", "/icons/icon-512.png"]),
      ),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("skatecue-pwa-") && key !== CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  // Session-dependent pages, RSC responses, APIs, and Clerk's requests stay network-only.
  // Only cache the app's public image assets; never cache authentication or video ranges.
  if (
    request.method !== "GET" ||
    url.origin !== self.location.origin ||
    request.headers.has("Range")
  )
    return;
  if (!/^\/(icons|media)\/.*\.(png|jpe?g|webp|svg)$/i.test(url.pathname))
    return;
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          void caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request)),
  );
});
