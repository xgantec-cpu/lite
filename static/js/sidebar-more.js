(function () {
  const groups = Array.from(document.querySelectorAll('[data-sidebar-more]'));

  if (!groups.length) return;

  function setOpen(group, open) {
    const toggle = group.querySelector('.sidebar-more-toggle');
    const menu = group.querySelector('[data-sidebar-more-menu]');
    if (!toggle || !menu) return;

    menu.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    group.classList.toggle('is-open', open);
  }

  groups.forEach(function (group) {
    const toggle = group.querySelector('.sidebar-more-toggle');
    const menu = group.querySelector('[data-sidebar-more-menu]');
    if (!toggle || !menu) return;

    setOpen(group, group.classList.contains('is-active'));
    toggle.addEventListener('click', function () {
      setOpen(group, menu.hidden);
    });
  });

  document.addEventListener('click', function (event) {
    groups.forEach(function (group) {
      if (!group.contains(event.target)) setOpen(group, false);
    });
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    groups.forEach(function (group) {
      setOpen(group, false);
    });
  });
})();
