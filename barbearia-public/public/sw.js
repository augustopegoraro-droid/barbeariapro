/* Service worker mínimo — só o necessário para instalabilidade (PWA).
   Network-first sem cache persistente de dados: agenda é dado vivo. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
