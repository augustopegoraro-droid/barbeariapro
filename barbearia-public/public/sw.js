/* Service worker mínimo — só o necessário para instalabilidade (PWA).
   Network-first sem cache persistente de dados: agenda é dado vivo.
   SW_VERSION força o update do worker instalado a cada mudança de tema
   (byte-diff → skipWaiting + clients.claim assumem na hora). */
const SW_VERSION = "v5-push-2026-08-14";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});

/* Notificações push (Web Push/VAPID) — confirmação de agendamento e
   lembretes (24h/30min). Payload: {title, body, url, tag}. */
self.addEventListener("push", (event) => {
  let data = { title: "Taylor e Thedy", body: "" };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch {
    /* payload não-JSON: mantém o default */
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      tag: data.tag,
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
