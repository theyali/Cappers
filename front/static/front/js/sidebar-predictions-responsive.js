(() => {
    const panel = document.querySelector(".latest-predictions-panel.sidebar-predictions");
    if (!panel) return;

    const sidebar = panel.closest(".coupon-sidebar");
    const toggle = panel.querySelector("[data-sidebar-toggle]");
    if (!sidebar || !toggle) return;

    const mobileQuery = window.matchMedia("(max-width: 1120px)");
    let userChangedState = false;

    const syncToggle = () => {
        const isCollapsed = sidebar.classList.contains("is-collapsed");
        toggle.setAttribute("aria-expanded", String(!isCollapsed));
        toggle.setAttribute("aria-label", isCollapsed ? "Развернуть прогнозы" : "Свернуть прогнозы");
    };

    const applyResponsiveDefault = () => {
        if (userChangedState) return;
        sidebar.classList.toggle("is-collapsed", mobileQuery.matches);
        syncToggle();
    };

    applyResponsiveDefault();

    toggle.addEventListener("click", () => {
        userChangedState = true;
        window.requestAnimationFrame(syncToggle);
    });

    mobileQuery.addEventListener?.("change", applyResponsiveDefault);
})();
