/*
 * Minimal Web Push worker for public district safety alerts.
 * It stores no case data and only displays the public alert payload.
 */
self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (error) {
    payload = {title: "Rapid Response alert", body: "A new safety message is available."};
  }
  const title = payload.title || "Rapid Response alert";
  const expiresAt = Date.parse(payload.expires_at || "");
  if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) return;
  const options = {
    body: payload.body || "A new safety message is available.",
    tag: `rapid-response-area-alert-${payload.alert_id || "general"}`,
    renotify: true,
    silent: false,
    vibrate: [350, 120, 350, 120, 700],
    actions: [{action: "open-alert", title: "View alert"}],
    icon: "/static/Rapid%20Response%20Emergency%20Logo.png",
    badge: "/static/Rapid%20Response%20Emergency%20Logo.png",
    timestamp: Date.parse(payload.created_at || "") || Date.now(),
    data: {url: payload.url || "/", payload, expires_at: payload.expires_at || ""},
  };
  event.waitUntil(Promise.all([
    self.registration.showNotification(title, options),
    self.clients.matchAll({type: "window", includeUncontrolled: true}).then((clients) => {
      clients.forEach((client) => client.postMessage({type: "PUBLIC_AREA_ALERT", payload}));
    }),
  ]));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  const expired = data.expires_at && Date.parse(data.expires_at) <= Date.now();
  const targetUrl = !expired && data.url ? data.url : "/alerts/";
  event.waitUntil(
    self.clients.matchAll({type: "window", includeUncontrolled: true}).then((clients) => {
      const existing = clients.find((client) => "focus" in client);
      if (existing) {
        existing.navigate(targetUrl);
        return existing.focus();
      }
      return self.clients.openWindow(targetUrl);
    }),
  );
});
