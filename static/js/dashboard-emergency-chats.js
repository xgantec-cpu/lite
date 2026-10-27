(() => {
  "use strict";

  const list = document.querySelector("[data-victim-chat-list]");
  const total = document.querySelector(".victim-chat-total");
  if (!list) return;

  const dashboardUrl = document.body.dataset.dashboardEmergencyChatsUrl;

  document.addEventListener("rapid-response:system-ping", (event) => {
    const chat = event.detail?.chats || {};
    const incidentId = chat.latest_incident_id;
    if (!incidentId || list.querySelector(`[data-victim-chat-case-id="${incidentId}"]`)) return;

    const empty = list.querySelector(".victim-chat-list-empty");
    empty?.remove();

    const link = document.createElement("a");
    link.className = "victim-chat-case has-unread is-live-arrival";
    link.dataset.victimChatCaseId = String(incidentId);
    link.href = `${dashboardUrl}?case=${encodeURIComponent(incidentId)}`;

    const avatar = document.createElement("span");
    avatar.className = "victim-chat-case-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = String(chat.latest_reference || "EMG").slice(-2);

    const copy = document.createElement("span");
    copy.className = "victim-chat-case-copy";
    const reference = document.createElement("strong");
    reference.textContent = chat.latest_reference || "New emergency chat";
    const detail = document.createElement("small");
    detail.textContent = `${chat.latest_area || "Location not tagged"} · ${chat.latest_emergency_type || "Emergency case"}`;
    const time = document.createElement("em");
    time.textContent = "Just now";
    copy.append(reference, detail, time);

    const unread = document.createElement("b");
    unread.className = "victim-chat-unread";
    unread.setAttribute("aria-label", "Unread chat");
    unread.textContent = "1";
    link.append(avatar, copy, unread);
    list.prepend(link);

    if (total) total.textContent = String(list.querySelectorAll("[data-victim-chat-case-id]").length);
  });
})();
