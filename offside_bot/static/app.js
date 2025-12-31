(() => {
  const body = document.body;
  if (!body) {
    return;
  }

  const CLASS_OPEN = "sidebar-open";
  const toggleSelector = "[data-sidebar-toggle]";
  const buttonSelector = "button[data-sidebar-toggle]";
  const mobileQuery = "(max-width: 900px)";

  const isMobile = () => window.matchMedia && window.matchMedia(mobileQuery).matches;

  const setOpen = (open) => {
    body.classList.toggle(CLASS_OPEN, open);
    const btn = document.querySelector(buttonSelector);
    if (btn) {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }
  };

  const toggle = () => setOpen(!body.classList.contains(CLASS_OPEN));

  document.addEventListener("click", (event) => {
    const target = event.target.closest(toggleSelector);
    if (!target) {
      return;
    }
    event.preventDefault();
    toggle();
  });

  document.addEventListener("click", (event) => {
    const nav = event.target.closest(".navlink");
    if (!nav) {
      return;
    }
    if (isMobile()) {
      setOpen(false);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setOpen(false);
    }
  });

  window.addEventListener("resize", () => {
    if (!isMobile()) {
      setOpen(false);
    }
  });
})();

