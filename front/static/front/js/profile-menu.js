(() => {
    const menu = document.querySelector("[data-profile-menu]");
    if (!menu) return;

    const toggle = menu.querySelector("[data-profile-menu-toggle]");
    const dropdown = menu.querySelector("[data-profile-menu-dropdown]");
    if (!toggle || !dropdown) return;

    const setOpen = (isOpen) => {
        menu.classList.toggle("is-open", isOpen);
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    };

    toggle.addEventListener("click", (event) => {
        event.stopPropagation();
        setOpen(!menu.classList.contains("is-open"));
    });

    dropdown.addEventListener("click", (event) => {
        event.stopPropagation();
    });

    document.addEventListener("click", () => setOpen(false));

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        setOpen(false);
        toggle.focus();
    });
})();
