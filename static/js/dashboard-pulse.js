/* Keep dashboard counters and live notifications current without refreshing the page. */
(() => {
  const page = document.body;
  const pulseUrl = page?.dataset.dashboardPulseUrl;
  if (!pulseUrl) return;
  const loginUrl = page?.dataset.dashboardLoginUrl;

  const notificationMenu = document.querySelector("[data-dashboard-notifications]");
  const notificationToggle = notificationMenu?.querySelector("[data-dashboard-notifications-toggle]");
  const notificationPanel = notificationMenu?.querySelector("[data-dashboard-notifications-panel]");
  const notificationList = notificationMenu?.querySelector("[data-dashboard-notifications-list]");
  const notificationCount = notificationMenu?.querySelector("[data-dashboard-notifications-count]");
  const badgeSelectors = {
    incoming: "[data-dashboard-nav-count]",
    referrals: "[data-dashboard-referral-count]",
    messages: "[data-dashboard-message-count]",
  };
  let snapshot = null;
  let requestInFlight = false;
  let pollingStopped = false;
  let pollTimer = null;
  let serverPendingCount = 0;
  let unreadNotifications = 0;
  const notifications = [];

  const setBadge = (selector, value) => {
    const badge = document.querySelector(selector);
    if (!badge) return;
    const count = Number(value) || 0;
    badge.textContent = count > 99 ? "99+" : String(count);
    badge.hidden = count < 1;
  };

  const dismissElement = (element) => {
    if (!element || element.dataset.removing === "true") return;
    element.dataset.removing = "true";
    element.classList.add("is-dismissing");
    window.setTimeout(() => element.remove(), 220);
  };

  const updateNotificationCount = () => {
    if (!notificationCount) return;
    notificationCount.textContent = unreadNotifications > 99 ? "99+" : String(unreadNotifications);
    notificationCount.hidden = unreadNotifications < 1;
  };

  const syncNotificationVisibility = () => {
    if (!notificationMenu) return;
    notificationMenu.hidden = serverPendingCount < 1 && notifications.length < 1;
    if (notificationMenu.hidden) closeNotificationMenu();
  };

  const formatNotificationTime = (date) => date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});

  const stopPollingForSession = () => {
    if (pollingStopped) return;
    pollingStopped = true;
    if (pollTimer) window.clearInterval(pollTimer);
    if (!loginUrl) return;
    const separator = loginUrl.includes("?") ? "&" : "?";
    window.location.assign(`${loginUrl}${separator}reason=inactive`);
  };

  const renderNotifications = () => {
    if (!notificationList) return;
    notificationList.replaceChildren();
    if (!notifications.length) {
      const empty = document.createElement("p");
      empty.className = "dashboard-notifications-empty";
      empty.textContent = "No new notifications.";
      notificationList.append(empty);
      return;
    }

    notifications.forEach((notification) => {
      const item = document.createElement("article");
      item.className = `dashboard-notification-item dashboard-notification-${notification.tone}${notification.unread ? " is-unread" : ""}`;

      const mark = document.createElement("span");
      mark.className = "dashboard-notification-mark";
      mark.textContent = notification.tone === "red" ? "!" : notification.tone === "orange" ? "↗" : "•";

      const content = document.createElement("div");
      content.className = "dashboard-notification-content";
      const title = document.createElement("strong");
      title.textContent = notification.title;
      const detail = document.createElement("span");
      detail.textContent = notification.detail;
      const time = document.createElement("small");
      time.textContent = notification.time;
      content.append(title, detail, time);

      const actions = document.createElement("div");
      actions.className = "dashboard-notification-actions";
      if (notification.href) {
        const open = document.createElement("a");
        open.className = "dashboard-notification-open";
        open.href = notification.href;
        open.textContent = "Open";
        open.addEventListener("click", () => {
          const index = notifications.indexOf(notification);
          if (index >= 0) notifications.splice(index, 1);
          if (notification.unread) unreadNotifications = Math.max(0, unreadNotifications - 1);
          updateNotificationCount();
          renderNotifications();
          syncNotificationVisibility();
        });
        actions.append(open);
      }
      const close = document.createElement("button");
      close.className = "dashboard-notification-dismiss";
      close.type = "button";
      close.setAttribute("aria-label", "Dismiss notification");
      close.textContent = "×";
      close.addEventListener("click", () => {
        const index = notifications.indexOf(notification);
        if (index >= 0) notifications.splice(index, 1);
        if (notification.unread) unreadNotifications = Math.max(0, unreadNotifications - 1);
        updateNotificationCount();
        renderNotifications();
        syncNotificationVisibility();
      });
      actions.append(close);
      item.append(mark, content, actions);
      notificationList.append(item);
    });
  };

  const addNotification = ({title, detail, href, tone = "blue", key}) => {
    if (!notificationList || notifications.some((notification) => notification.key === key)) return;
    notifications.unshift({title, detail, href, tone, key, unread: true, time: formatNotificationTime(new Date())});
    if (notifications.length > 20) notifications.pop();
    unreadNotifications = Math.min(unreadNotifications + 1, 99);
    renderNotifications();
    updateNotificationCount();
    syncNotificationVisibility();
  };

  const closeNotificationMenu = () => {
    if (!notificationPanel || !notificationToggle) return;
    notificationPanel.hidden = true;
    notificationToggle.setAttribute("aria-expanded", "false");
    notificationMenu?.classList.remove("is-open");
  };

  const openNotificationMenu = () => {
    if (!notificationPanel || !notificationToggle) return;
    notificationPanel.hidden = false;
    notificationToggle.setAttribute("aria-expanded", "true");
    notificationMenu?.classList.add("is-open");
    unreadNotifications = 0;
    notifications.forEach((notification) => { notification.unread = false; });
    updateNotificationCount();
    renderNotifications();
  };

  notificationToggle?.addEventListener("click", () => {
    if (notificationPanel?.hidden) openNotificationMenu();
    else closeNotificationMenu();
  });
  notificationMenu?.querySelector("[data-dashboard-notifications-close]")?.addEventListener("click", closeNotificationMenu);
  document.addEventListener("click", (event) => {
    if (notificationMenu && !notificationMenu.contains(event.target)) closeNotificationMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeNotificationMenu();
  });

  const poll = async () => {
    if (pollingStopped || requestInFlight || document.visibilityState === "hidden") return;
    requestInFlight = true;
    try {
      const response = await fetch(pulseUrl, {
        credentials: "same-origin",
        headers: {"X-Requested-With": "XMLHttpRequest", Accept: "application/json"},
        cache: "no-store",
      });
      if (response.status === 401 || response.redirected) {
        stopPollingForSession();
        return;
      }
      if (!response.ok) return;
      if (!response.headers.get("content-type")?.includes("application/json")) {
        stopPollingForSession();
        return;
      }
      const data = await response.json();
      document.dispatchEvent(new CustomEvent("rapid-response:system-ping", {detail: data}));
      const incoming = data.incoming || {};
      const referrals = data.referrals || {};
      const messages = data.messages || {};
      serverPendingCount = (Number(incoming.count) || 0) + (Number(referrals.unread) || 0) + (Number(messages.unread) || 0);
      setBadge(badgeSelectors.incoming, incoming.count);
      setBadge(badgeSelectors.referrals, referrals.unread);
      setBadge(badgeSelectors.messages, messages.unread);
      syncNotificationVisibility();

      if (snapshot) {
        if (incoming.latest_id && incoming.latest_id !== snapshot.incoming.latest_id) {
          addNotification({
            title: "New emergency case",
            detail: `${incoming.latest_reference || "A new case"} · ${incoming.latest_area || "Assigned area"}`,
            href: page.dataset.dashboardIncomingUrl,
            tone: incoming.latest_priority === "critical" ? "red" : "orange",
            key: `incoming-${incoming.latest_id}`,
          });
        }
        if (referrals.latest_id && referrals.latest_id !== snapshot.referrals.latest_id) {
          addNotification({
            title: "New referral received",
            detail: "A case transfer is waiting in your referral inbox.",
            href: page.dataset.dashboardReferralsUrl,
            tone: "orange",
            key: `referral-${referrals.latest_id}`,
          });
        }
        if (messages.latest_id && messages.latest_id !== snapshot.messages.latest_id) {
          addNotification({
            title: "New official message",
            detail: "A responder or institution sent you a message.",
            href: page.dataset.dashboardChatUrl,
            tone: "blue",
            key: `message-${messages.latest_id}`,
          });
        }
      } else {
        if (incoming.count) {
          addNotification({
            title: `${incoming.count} emergency case${incoming.count === 1 ? "" : "s"} waiting`,
            detail: "Unopened cases are ready in your attention queue.",
            href: page.dataset.dashboardIncomingUrl,
            tone: incoming.latest_priority === "critical" ? "red" : "orange",
            key: `pending-incoming-${incoming.latest_id || incoming.count}`,
          });
        }
        if (referrals.unread) {
          addNotification({
            title: `${referrals.unread} referral${referrals.unread === 1 ? "" : "s"} waiting`,
            detail: "Open your referral inbox to review transferred cases.",
            href: page.dataset.dashboardReferralsUrl,
            tone: "orange",
            key: `pending-referrals-${referrals.latest_id || referrals.unread}`,
          });
        }
        if (messages.unread) {
          addNotification({
            title: `${messages.unread} unread official message${messages.unread === 1 ? "" : "s"}`,
            detail: "Open the official chat to continue the conversation.",
            href: page.dataset.dashboardChatUrl,
            tone: "blue",
            key: `pending-messages-${messages.latest_id || messages.unread}`,
          });
        }
      }
      snapshot = {incoming, referrals, messages};
    } catch (error) {
      // The next ping retries after a temporary network interruption.
    } finally {
      requestInFlight = false;
    }
  };

  document.querySelectorAll("[data-flash]").forEach((flash) => {
    const close = flash.querySelector("[data-flash-close]");
    close?.addEventListener("click", () => dismissElement(flash));
    window.setTimeout(() => dismissElement(flash), 4800);
  });

  renderNotifications();
  updateNotificationCount();
  syncNotificationVisibility();
  poll();
  pollTimer = window.setInterval(poll, 5000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") poll();
  });
})();
