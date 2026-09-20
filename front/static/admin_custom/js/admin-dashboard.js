(() => {
    const body = document.body;
    if (!body?.classList.contains("cappers-admin")) return;

    const search = document.querySelector("[data-admin-search]");
    const appCards = Array.from(document.querySelectorAll("[data-admin-app-card]"));
    const appGroups = Array.from(document.querySelectorAll("[data-admin-app-group]"));
    const emptyState = document.querySelector("[data-admin-search-empty]");
    const toggles = Array.from(document.querySelectorAll("[data-admin-sidebar-toggle]"));
    const themeToggle = document.querySelector("[data-admin-theme-toggle]");

    const normalize = (value) => String(value || "").trim().toLowerCase();

    const applySearch = () => {
        const query = normalize(search?.value);
        let visibleCards = 0;

        appCards.forEach((card) => {
            const matches = !query || normalize(card.dataset.search).includes(query);
            card.hidden = !matches;
            if (matches) visibleCards += 1;
        });

        appGroups.forEach((group) => {
            const appMatches = !query || normalize(group.dataset.adminAppSearch).includes(query);
            const modelItems = Array.from(group.querySelectorAll("[data-admin-model-item]"));
            const hasModelMatch = modelItems.some((item) => (
                !query || normalize(item.dataset.adminModelSearch).includes(query)
            ));

            group.hidden = Boolean(query) && !appMatches && !hasModelMatch;
        });

        if (emptyState) {
            emptyState.hidden = !query || visibleCards > 0;
        }
    };

    search?.addEventListener("input", applySearch);

    document.addEventListener("keydown", (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            search?.focus();
        }

        if (event.key === "Escape" && body.classList.contains("cappers-admin-sidebar-open")) {
            body.classList.remove("cappers-admin-sidebar-open");
            toggles.forEach((toggle) => toggle.setAttribute("aria-expanded", "false"));
        }
    });

    const toggleSidebar = () => {
        const isOpen = body.classList.toggle("cappers-admin-sidebar-open");
        toggles.forEach((toggle) => toggle.setAttribute("aria-expanded", String(isOpen)));
    };

    toggles.forEach((toggle) => {
        toggle.addEventListener("click", toggleSidebar);
    });

    themeToggle?.addEventListener("click", () => {
        document.querySelector(".theme-toggle")?.click();
    });

    document.querySelectorAll("#nav-sidebar a").forEach((link) => {
        link.addEventListener("click", () => {
            body.classList.remove("cappers-admin-sidebar-open");
        });
    });
})();
