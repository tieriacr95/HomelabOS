/* HomeLab OS PWA: only public, immutable frontend assets are cached.
 * NEVER cache HTML, authentication, sessions, API data or sensitive content.
 */
const VERSION = "homelabos-static-v0.6.5";
const ASSETS = ["/assets/app.js", "/assets/app.css", "/pwa/icon-192.png",
                "/pwa/icon-512.png", "/manifest.webmanifest"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(VERSION).then(cache => cache.addAll(ASSETS)));
  self.skipWaiting();
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(key => key.startsWith("homelabos-static-") && key !== VERSION)
                    .map(key => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET" || request.mode === "navigate") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // No API, no login, no cookies/session data, no dynamic HTML in storage.
  if (!/^\/(assets\/app\.(js|css)|pwa\/icon-(192|512)\.png|manifest\.webmanifest)$/.test(url.pathname)) return;
  event.respondWith(caches.match(request).then(cached => cached || fetch(request)));
});
