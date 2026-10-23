(() => {
  const panel = document.querySelector("[data-public-alerts]");
  if (!panel) return;

  const publicKey = panel.dataset.publicKey || "";
  const subscribeUrl = panel.dataset.subscribeUrl;
  const unsubscribeUrl = panel.dataset.unsubscribeUrl;
  const areaSelect = panel.querySelector("[data-alert-area]");
  const enableButton = panel.querySelector("[data-alert-enable]");
  const disableButton = panel.querySelector("[data-alert-disable]");
  const status = panel.querySelector("[data-alert-status]");
  const csrfToken = document.querySelector("input[name=csrfmiddlewaretoken]")?.value || "";
  const clientUuid = document.getElementById("id_client_uuid")?.value || "";

  const setStatus = (message, state = "") => {
    status.textContent = message;
    status.dataset.state = state;
  };

  const readablePushError = (error, fallback) => {
    const message = error?.message || "";
    if (/push service/i.test(message)) {
      const safari = /Safari/i.test(navigator.userAgent) && !/Chrome|CriOS|Edg/i.test(navigator.userAgent);
      return safari
        ? "Safari Web Push requires HTTPS and, on iPhone or iPad, adding this site to the Home Screen."
        : "This browser's push service rejected the subscription. Confirm HTTPS and the matching VAPID keys, then reload.";
    }
    return message || fallback;
  };

  const showCriticalAlert = (payload = {}) => {
    const existing = document.querySelector("[data-critical-alert]");
    if (existing) existing.remove();

    const overlay = document.createElement("section");
    overlay.className = "critical-alert-overlay";
    overlay.dataset.criticalAlert = "";
    overlay.setAttribute("role", "alertdialog");
    overlay.setAttribute("aria-modal", "false");
    overlay.setAttribute("aria-live", "assertive");

    const header = document.createElement("div");
    header.className = "critical-alert-header";
    const label = document.createElement("span");
    label.className = "critical-alert-label";
    label.textContent = "CRITICAL PUBLIC SAFETY ALERT";
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "critical-alert-close";
    closeButton.setAttribute("aria-label", "Close alert");
    closeButton.textContent = "×";
    closeButton.addEventListener("click", () => overlay.remove());
    header.append(label, closeButton);

    const title = document.createElement("h2");
    title.textContent = payload.title || "Urgent safety information";
    const body = document.createElement("p");
    body.textContent = payload.body || "Please follow the instructions from the response team.";
    const area = document.createElement("span");
    area.className = "critical-alert-area";
    area.textContent = payload.national
      ? "Audience: Uganda · Whole country"
      : (payload.area ? `District: ${payload.area}` : "District safety notice");
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "critical-alert-open";
    openButton.textContent = "Open safety notice";
    openButton.addEventListener("click", () => {
      window.location.href = payload.url || "/";
    });

    overlay.append(header, title, body, area, openButton);
    document.body.appendChild(overlay);
    const expiresAt = Date.parse(payload.expires_at || "");
    if (Number.isFinite(expiresAt)) {
      const remaining = expiresAt - Date.now();
      if (remaining <= 0) overlay.remove();
      else window.setTimeout(() => overlay.remove(), remaining);
    }
  };

  const decodeKey = (value) => {
    const normalized = value.trim().replace(/^['"]|['"]$/g, "").replace(/\s/g, "").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const padding = "=".repeat((4 - (normalized.length % 4)) % 4);
    const base64 = (normalized + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = window.atob(base64);
    if (raw.length !== 65 || raw.charCodeAt(0) !== 4) {
      throw new Error("The Web Push public key is invalid. Check WEBPUSH_VAPID_PUBLIC_KEY.");
    }
    return Uint8Array.from(raw, (character) => character.charCodeAt(0));
  };

  const send = async (url, payload) => {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken},
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "The alert preference could not be saved.");
    return data;
  };

  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (!supported) {
    enableButton.disabled = true;
    setStatus("This browser does not support browser safety alerts.");
    return;
  }
  if (!publicKey) {
    enableButton.disabled = true;
    setStatus("Local alerts will be available after Web Push is configured.");
    return;
  }

  let registration;
  let serviceWorkerError = "";
  const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  if (!window.isSecureContext && !localHost) {
    serviceWorkerError = "Browser alerts require HTTPS (or localhost) and a supported browser.";
    enableButton.disabled = true;
    setStatus(serviceWorkerError, "error");
  } else {
    navigator.serviceWorker.register("/service-worker.js", {scope: "/", updateViaCache: "none"})
      .then(() => navigator.serviceWorker.ready)
      .then((value) => {
        registration = value;
        navigator.serviceWorker.addEventListener("message", (event) => {
          if (event.data?.type === "PUBLIC_AREA_ALERT") showCriticalAlert(event.data.payload);
        });
      })
      .catch((error) => {
        console.error("Public alert service worker registration failed.", error);
        serviceWorkerError = "Browser alerts could not start. Use HTTPS, then reload this page.";
        enableButton.disabled = true;
        setStatus(serviceWorkerError, "error");
      });
  }

  const updateButtons = (subscribed) => {
    enableButton.hidden = subscribed;
    disableButton.hidden = !subscribed;
  };

  enableButton.addEventListener("click", async () => {
    const areaId = areaSelect.value;
    if (!areaId) {
      setStatus("Choose the district where you want to receive alerts.", "error");
      areaSelect.focus();
      return;
    }
    enableButton.disabled = true;
    setStatus("Preparing secure browser alerts…");
    try {
      if (serviceWorkerError) throw new Error(serviceWorkerError);
      if (!registration) registration = await navigator.serviceWorker.ready;
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Browser permission was not granted.");
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        const applicationServerKey = decodeKey(publicKey);
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey,
        });
      }
      const subscriptionJson = subscription.toJSON();
      const result = await send(subscribeUrl, {
        area_id: areaId,
        endpoint: subscriptionJson.endpoint,
        keys: subscriptionJson.keys,
        client_uuid: clientUuid,
      });
      updateButtons(true);
      setStatus(`You will receive public safety alerts for ${result.area}.`, "success");
      panel.hidden = true;
    } catch (error) {
      setStatus(readablePushError(error, "Alerts could not be enabled."), "error");
      enableButton.disabled = false;
    }
  });

  disableButton.addEventListener("click", async () => {
    disableButton.disabled = true;
    try {
      if (!registration) registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        await send(unsubscribeUrl, {endpoint: subscription.endpoint});
        await subscription.unsubscribe();
      }
      updateButtons(false);
      setStatus("District safety alerts are turned off.");
      enableButton.disabled = false;
    } catch (error) {
      setStatus(error.message || "Alerts could not be turned off.", "error");
      disableButton.disabled = false;
    }
  });
})();
