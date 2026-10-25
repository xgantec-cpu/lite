(() => {
  const guide = document.querySelector("[data-admin-guide]");
  if (!guide) return;

  const userId = guide.dataset.userId || "unknown";
  const storageKey = `rapid-response-admin-guide-seen:${userId}`;
  const closeButtons = guide.querySelectorAll("[data-admin-guide-close]");

  const closeGuide = () => {
    guide.hidden = true;
    document.body.classList.remove("admin-guide-open");
    try { window.localStorage.setItem(storageKey, "1"); } catch (error) {}
  };

  let alreadySeen = false;
  try { alreadySeen = window.localStorage.getItem(storageKey) === "1"; } catch (error) {}
  if (!alreadySeen) {
    guide.hidden = false;
    document.body.classList.add("admin-guide-open");
  }

  closeButtons.forEach((button) => button.addEventListener("click", closeGuide));
  guide.addEventListener("click", (event) => {
    if (event.target === guide) closeGuide();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !guide.hidden) closeGuide();
  });
})();
