/* Floating official case chat with lightweight polling and no page reloads. */
(function () {
  const widget = document.querySelector("[data-chat-widget]");
  if (!widget) return;

  const launcher = widget.querySelector("[data-chat-launcher]");
  const panel = widget.querySelector("[data-chat-panel]");
  const closeButton = widget.querySelector("[data-chat-close]");
  const expandButton = widget.querySelector("[data-chat-expand]");
  const form = widget.querySelector("[data-chat-form]");
  const bodyField = widget.querySelector("[data-chat-body]");
  const messages = widget.querySelector("[data-chat-messages]");
  const badge = widget.querySelector("[data-chat-unread]");
  const referralSelect = widget.querySelector("[data-chat-referral]");
  const urlTemplate = widget.dataset.chatUrlTemplate;
  const websocketUrlTemplate = widget.dataset.chatWsUrlTemplate;
  const csrfToken = widget.dataset.csrf;
  let isOpen = false;
  let isExpanded = false;
  let socket;
  let reconnectTimer;

  document.querySelectorAll(".case-communication-card, .institution-chat").forEach((legacyChat) => {
    legacyChat.hidden = true;
  });

  function currentUrl(markRead) {
    const referralId = referralSelect ? referralSelect.value : widget.dataset.referralId;
    return urlTemplate.replace("/0/", "/" + referralId + "/") + (markRead ? "?open=1" : "");
  }

  function currentWebsocketUrl() {
    const referralId = referralSelect ? referralSelect.value : widget.dataset.referralId;
    const path = websocketUrlTemplate.replace("/0/", "/" + referralId + "/");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return protocol + "//" + window.location.host + path;
  }

  function setUnread(count) {
    badge.textContent = count > 99 ? "99+" : String(count);
    badge.hidden = count < 1;
    launcher.classList.toggle("has-unread", count > 0);
  }

  function setExpanded(expanded) {
    isExpanded = expanded;
    panel.classList.toggle("is-expanded", expanded);
    document.body.classList.toggle("chat-panel-expanded", expanded);
    if (!expandButton) return;
    expandButton.setAttribute("aria-expanded", String(expanded));
    expandButton.setAttribute("aria-label", expanded ? "Collapse chat" : "Expand chat");
    expandButton.textContent = expanded ? "↙" : "↗";
  }

  function renderMessages(items) {
    messages.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "official-chat-empty";
      empty.textContent = "No messages yet. Start the official case conversation.";
      messages.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const message = document.createElement("article");
      message.className = "official-chat-message" + (item.mine ? " mine" : "");
      const text = document.createElement("p");
      text.textContent = item.body;
      const meta = document.createElement("small");
      meta.textContent = item.sender + " · " + item.created_at;
      message.append(text, meta);
      messages.appendChild(message);
    });
    messages.scrollTop = messages.scrollHeight;
  }

  async function refresh(markRead) {
    try {
      const response = await fetch(currentUrl(markRead), {headers: {"X-Requested-With": "XMLHttpRequest"}});
      if (!response.ok) return;
      const data = await response.json();
      renderMessages(data.messages || []);
      setUnread(data.unread || 0);
    } catch (error) {
      // A temporary network interruption should not lock the case page.
    }
  }

  function connectWebSocket() {
    if (!websocketUrlTemplate || !window.WebSocket || (socket && socket.readyState === WebSocket.OPEN)) return;
    const selectedReferral = referralSelect ? referralSelect.value : widget.dataset.referralId;
    socket = new WebSocket(currentWebsocketUrl());
    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({action: "sync"}));
      refresh(isOpen);
    });
    socket.addEventListener("message", (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "chat.state") {
        renderMessages(data.state.messages || []);
        setUnread(data.state.unread || 0);
      }
      if (data.type === "chat.refresh") refresh(isOpen);
    });
    socket.addEventListener("close", (event) => {
      socket = null;
      if ([4001, 4403, 4404].includes(event.code)) return;
      window.clearTimeout(reconnectTimer);
      reconnectTimer = window.setTimeout(() => {
        const currentReferral = referralSelect ? referralSelect.value : widget.dataset.referralId;
        if (currentReferral === selectedReferral) connectWebSocket();
      }, 3000);
    });
  }

  launcher.addEventListener("click", () => {
    isOpen = !isOpen;
    panel.hidden = !isOpen;
    launcher.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) {
      refresh(true);
      bodyField.focus();
    }
  });
  closeButton.addEventListener("click", () => {
    isOpen = false;
    panel.hidden = true;
    setExpanded(false);
    launcher.setAttribute("aria-expanded", "false");
  });
  if (expandButton) expandButton.addEventListener("click", () => setExpanded(!isExpanded));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isExpanded) setExpanded(false);
  });
  if (referralSelect) referralSelect.addEventListener("change", () => {
    if (socket) socket.close();
    refresh(isOpen);
    connectWebSocket();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = bodyField.value.trim();
    if (!body) return;
    const payload = new URLSearchParams({
      body,
      idempotency_key: window.crypto && window.crypto.randomUUID
        ? window.crypto.randomUUID()
        : String(Date.now()) + "-" + Math.random().toString(16).slice(2),
    });
    const response = await fetch(currentUrl(""), {
      method: "POST",
      headers: {"X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded"},
      body: payload,
    });
    if (response.ok) {
      bodyField.value = "";
      await refresh(true);
    }
  });

  refresh(false);
  connectWebSocket();
  window.setInterval(() => {
    if (!socket || socket.readyState !== WebSocket.OPEN) refresh(isOpen);
  }, 5000);
  window.setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({action: "presence"}));
  }, 60000);
}());
