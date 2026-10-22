/* Lock authenticated workspaces after five quiet minutes, but stay open while active. */
(function () {
  const lockUrl = document.body.dataset.sessionLockUrl;
  const keepAliveUrl = document.body.dataset.sessionKeepaliveUrl;
  if (!lockUrl) return;
  const timeoutMs = 5 * 60 * 1000;
  const keepAliveIntervalMs = 60 * 1000;
  let timer;
  let lastActivity = Date.now();
  let lastKeepAlive = 0;

  function keepAlive() {
    const now = Date.now();
    if (!keepAliveUrl || now - lastActivity >= timeoutMs || now - lastKeepAlive < keepAliveIntervalMs) return;
    lastKeepAlive = now;
    fetch(keepAliveUrl, {
      credentials: "same-origin",
      headers: {Accept: "application/json"},
      cache: "no-store",
    }).then((response) => {
      if (response.status === 401 || response.redirected) window.location.assign(lockUrl + "?reason=inactivity");
    }).catch(() => {});
  }

  function arm() {
    window.clearTimeout(timer);
    lastActivity = Date.now();
    timer = window.setTimeout(() => {
      window.location.assign(lockUrl + "?reason=inactivity");
    }, timeoutMs);
    keepAlive();
  }
  ["pointerdown", "keydown", "scroll", "touchstart", "mousemove"].forEach((eventName) => {
    window.addEventListener(eventName, arm, {passive: true});
  });
  arm();
  window.setInterval(keepAlive, keepAliveIntervalMs);
}());
