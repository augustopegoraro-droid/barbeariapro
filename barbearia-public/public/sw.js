/* Service worker mínimo — só o necessário para instalabilidade (PWA).
   Network-first sem cache persistente de dados: agenda é dado vivo.
   SW_VERSION força o update do worker instalado a cada mudança de tema
   (byte-diff → skipWaiting + clients.claim assumem na hora). */
const SW_VERSION = "v4-landing-ouro-2026-07-24";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
