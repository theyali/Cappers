(() => {
    const menus = Array.from(document.querySelectorAll("[data-profile-menu]"));
    if (!menus.length) return;

    const closeTimers = new WeakMap();

    const setOpen = (menu, isOpen) => {
        const toggle = menu.querySelector("[data-profile-menu-toggle]");
        window.clearTimeout(closeTimers.get(menu));
        menu.classList.toggle("is-open", isOpen);
        if (toggle) {
            toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        }
    };

    const scheduleClose = (menu) => {
        window.clearTimeout(closeTimers.get(menu));
        closeTimers.set(menu, window.setTimeout(() => setOpen(menu, false), 180));
    };

    menus.forEach((menu) => {
        const toggle = menu.querySelector("[data-profile-menu-toggle]");
        const dropdown = menu.querySelector("[data-profile-menu-dropdown]");
        if (!toggle || !dropdown) return;

        menu.addEventListener("pointerenter", () => setOpen(menu, true));
        menu.addEventListener("pointerleave", () => scheduleClose(menu));
        menu.addEventListener("focusin", () => setOpen(menu, true));
        menu.addEventListener("focusout", () => scheduleClose(menu));

        toggle.addEventListener("click", (event) => {
            event.stopPropagation();
            setOpen(menu, !menu.classList.contains("is-open"));
        });

        dropdown.addEventListener("click", (event) => {
            event.stopPropagation();
        });
    });

    document.addEventListener("click", () => {
        menus.forEach((menu) => setOpen(menu, false));
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        menus.forEach((menu) => setOpen(menu, false));
        const activeMenu = document.activeElement?.closest?.("[data-profile-menu]");
        activeMenu?.querySelector("[data-profile-menu-toggle]")?.focus();
    });
})();
