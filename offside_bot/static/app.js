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

  const commandsSearch = document.getElementById("commands-search");
  if (commandsSearch) {
    const filterButtons = Array.from(document.querySelectorAll("[data-commands-filter]"));
    const commandCards = Array.from(document.querySelectorAll("[data-command-card]"));
    const sections = Array.from(document.querySelectorAll("[data-commands-section]"));
    const empty = document.getElementById("commands-empty");
    const count = document.getElementById("commands-count");

    let activeFilter = "all";

    const applyCommandsFilter = () => {
      const query = (commandsSearch.value || "").trim().toLowerCase();
      const sectionCounts = new Map();
      let visible = 0;

      commandCards.forEach((card) => {
        const group = (card.dataset.commandsGroup || "other").toLowerCase();
        const blob = (card.dataset.commandsSearch || "").toLowerCase();
        const matchesFilter = activeFilter === "all" || group === activeFilter;
        const matchesSearch = !query || blob.includes(query);
        const show = matchesFilter && matchesSearch;

        card.style.display = show ? "" : "none";

        const section = card.closest("[data-commands-section]");
        if (show && section) {
          sectionCounts.set(section, (sectionCounts.get(section) || 0) + 1);
          visible += 1;
        }
      });

      sections.forEach((section) => {
        const n = sectionCounts.get(section) || 0;
        section.style.display = n > 0 ? "" : "none";
      });

      if (count) {
        count.textContent = `${visible} command${visible === 1 ? "" : "s"} shown`;
      }

      if (empty) {
        empty.style.display = visible ? "none" : "";
      }
    };

    const setCommandsFilter = (value) => {
      activeFilter = (value || "all").toLowerCase();
      filterButtons.forEach((btn) => {
        const btnFilter = (btn.dataset.commandsFilter || "all").toLowerCase();
        const isActive = btnFilter === activeFilter;
        btn.classList.toggle("blue", isActive);
        btn.classList.toggle("secondary", !isActive);
      });
      applyCommandsFilter();
    };

    commandsSearch.addEventListener("input", applyCommandsFilter);
    filterButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        setCommandsFilter(btn.dataset.commandsFilter || "all");
      });
    });

    setCommandsFilter("all");
  }

  const guildSearch = document.getElementById("guild-search");
  if (guildSearch) {
    const guildCards = Array.from(document.querySelectorAll(".guild-card"));
    guildSearch.addEventListener("input", () => {
      const term = (guildSearch.value || "").toLowerCase();
      guildCards.forEach((card) => {
        const name = (card.dataset.name || "").toLowerCase();
        card.style.display = !term || name.includes(term) ? "" : "none";
      });
    });
  }

  const copyToClipboard = async (text, input) => {
    if (!text) {
      return false;
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      // fall back below
    }

    if (input && input.select) {
      input.focus();
      input.select();
    }
    try {
      return document.execCommand && document.execCommand("copy");
    } catch {
      return false;
    }
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-text]");
    if (!button) {
      return;
    }
    event.preventDefault();
    const text = button.getAttribute("data-copy-text") || "";
    const input = button.parentElement && button.parentElement.querySelector(".copy-input");
    const ok = await copyToClipboard(text, input);

    const previous = button.textContent || "Copy";
    button.textContent = ok ? "Copied" : "Copy failed";
    window.setTimeout(() => {
      button.textContent = previous;
    }, 1200);
  });

  document.addEventListener("focusin", (event) => {
    const input = event.target;
    if (!input || !(input instanceof HTMLInputElement)) {
      return;
    }
    if (input.classList.contains("copy-input")) {
      input.select();
    }
  });
})();
