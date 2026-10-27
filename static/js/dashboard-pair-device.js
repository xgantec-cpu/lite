(() => {
  const page = document.querySelector("[data-admin-pair-device]");
  if (!page) return;
  const startButton = page.querySelector("[data-pair-device-start]");
  const status = page.querySelector("[data-pair-device-status]");
  const publicKey = page.dataset.publicKey || "";
  const csrfToken = page.dataset.csrf || "";

  const setStatus = (message, state = "") => {
    status.textContent = message;
    status.dataset.state = state;
  };

  const decodeKey = (value) => {
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const decoded = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
  };

  const pairBrowser = async () => {
    if (!publicKey) throw new Error("Web Push is not configured on this server yet.");
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      throw new Error("This browser does not support secure notifications.");
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("Notification permission was not granted.");
    await navigator.serviceWorker.register("/service-worker.js", {scope: "/", updateViaCache: "none"});
    const readyRegistration = await navigator.serviceWorker.ready;
    let subscription = await readyRegistration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await readyRegistration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeKey(publicKey),
      });
    }
    const subscriptionJson = subscription.toJSON();
    const response = await fetch(page.dataset.pairEndpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest"},
      body: JSON.stringify({
        endpoint: subscriptionJson.endpoint,
        keys: subscriptionJson.keys,
        device_label: `${navigator.platform || "Admin"} browser`,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "This browser could not be paired.");
    return result;
  };

  startButton.addEventListener("click", async () => {
    startButton.disabled = true;
    setStatus("Requesting secure notification permission…");
    try {
      const result = await pairBrowser();
      setStatus(`${result.device_label} is paired. This browser will receive critical backlog alerts.`, "success");
      startButton.hidden = true;
    } catch (error) {
      setStatus(error.message || "The browser could not be paired.", "error");
      startButton.disabled = false;
    }
  });
})();
