(() => {
    const TAB_PANELS = {
        predictions: [".expert-public-predictions"],
        stats: [
            ".expert-recent-performance",
            ".expert-public-analytics",
            ".expert-sport-profit",
            ".expert-monthly-stats",
        ],
        achievements: ['[data-expert-public-panel="achievements"]'],
        tournaments: ['[data-expert-public-panel="tournaments"]'],
    };
    const TAB_NAMES = Object.keys(TAB_PANELS);
    const MANAGED_PANEL_SELECTOR = Array.from(
        new Set(Object.values(TAB_PANELS).flat())
    ).join(",");

    function initExpertTabs(root) {
        const buttons = Array.from(root.querySelectorAll("[data-expert-public-tab]"));
        if (!buttons.length) return;

        const setPanelVisibility = (tabName) => {
            const visibleSelectors = TAB_PANELS[tabName] || [];
            root.querySelectorAll(MANAGED_PANEL_SELECTOR).forEach((panel) => {
                const isVisible = visibleSelectors.some((selector) => panel.matches(selector));
                panel.hidden = !isVisible;
            });
        };

        const setActiveTab = (tabName, focusButton = false) => {
            if (!TAB_NAMES.includes(tabName)) return;

            root.dataset.activeTab = tabName;
            setPanelVisibility(tabName);

            buttons.forEach((button) => {
                const isActive = button.dataset.expertPublicTab === tabName;
                button.classList.toggle("is-active", isActive);
                button.setAttribute("aria-selected", isActive ? "true" : "false");
                button.tabIndex = isActive ? 0 : -1;

                if (isActive && focusButton) {
                    button.focus();
                }
            });
        };

        buttons.forEach((button, index) => {
            button.addEventListener("click", () => {
                setActiveTab(button.dataset.expertPublicTab);
            });

            button.addEventListener("keydown", (event) => {
                let nextIndex = null;

                if (event.key === "ArrowRight") {
                    nextIndex = (index + 1) % buttons.length;
                } else if (event.key === "ArrowLeft") {
                    nextIndex = (index - 1 + buttons.length) % buttons.length;
                } else if (event.key === "Home") {
                    nextIndex = 0;
                } else if (event.key === "End") {
                    nextIndex = buttons.length - 1;
                }

                if (nextIndex === null) return;

                event.preventDefault();
                setActiveTab(buttons[nextIndex].dataset.expertPublicTab, true);
            });
        });

        setActiveTab(root.dataset.activeTab || "predictions");
    }

    const init = () => {
        document.querySelectorAll("[data-expert-public-tabs]").forEach(initExpertTabs);
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
