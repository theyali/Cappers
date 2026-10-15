(() => {
    const TAB_PANELS = {
        predictions: [
            ".expert-public-hero",
            ".expert-public-stats-compact",
            ".expert-public-latest-articles",
            ".expert-public-predictions:not([data-expert-public-panel])",
        ],
        stats: [
            ".expert-recent-performance",
            ".expert-public-analytics",
            ".expert-sport-profit",
            ".expert-monthly-stats",
        ],
        bank: ['[data-expert-public-panel="bank"]'],
        achievements: ['[data-expert-public-panel="achievements"]'],
        tournaments: ['[data-expert-public-panel="tournaments"]'],
        articles: ['[data-expert-public-panel="articles"]'],
    };
    const TAB_NAMES = Object.keys(TAB_PANELS);
    const MANAGED_PANEL_SELECTOR = Array.from(
        new Set(Object.values(TAB_PANELS).flat())
    ).join(",");

    function initExpertTabs(root) {
        const buttons = Array.from(root.querySelectorAll('[role="tab"][data-expert-public-tab]'));
        const panels = Array.from(root.querySelectorAll(MANAGED_PANEL_SELECTOR));
        if (!buttons.length) return;

        const setPanelVisibility = (tabName) => {
            const visibleSelectors = TAB_PANELS[tabName] || [];
            panels.forEach((panel) => {
                const isVisible = visibleSelectors.some((selector) => panel.matches(selector));
                panel.hidden = !isVisible;

                if (isVisible) {
                    panel.style.removeProperty("display");
                } else {
                    panel.style.setProperty("display", "none", "important");
                }
            });
        };

        const setActiveTab = (tabName, focusButton = null, updateHash = false) => {
            if (!TAB_NAMES.includes(tabName)) return;

            root.dataset.activeTab = tabName;
            setPanelVisibility(tabName);

            buttons.forEach((button) => {
                const isActive = button.dataset.expertPublicTab === tabName;
                button.classList.toggle("is-active", isActive);
                button.setAttribute("aria-selected", isActive ? "true" : "false");
                button.tabIndex = isActive ? 0 : -1;
            });
            if (focusButton) focusButton.focus();
            if (updateHash) window.history.replaceState(null, "", `#${tabName}`);
        };

        buttons.forEach((button) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                setActiveTab(button.dataset.expertPublicTab, null, true);
            });

            button.addEventListener("keydown", (event) => {
                if (event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
                const tablist = button.closest('[role="tablist"]');
                const siblings = buttons.filter((candidate) => candidate.closest('[role="tablist"]') === tablist);
                const index = siblings.indexOf(button);
                let nextIndex = null;

                if (event.key === "ArrowRight") {
                    nextIndex = (index + 1) % siblings.length;
                } else if (event.key === "ArrowLeft") {
                    nextIndex = (index - 1 + siblings.length) % siblings.length;
                } else if (event.key === "Home") {
                    nextIndex = 0;
                } else if (event.key === "End") {
                    nextIndex = siblings.length - 1;
                } else if (event.key === " ") {
                    nextIndex = index;
                }

                if (nextIndex === null) return;

                event.preventDefault();
                const nextButton = siblings[nextIndex];
                setActiveTab(nextButton.dataset.expertPublicTab, nextButton, true);
            });
        });

        root.addEventListener("click", (event) => {
            const trigger = event.target.closest("[data-expert-public-open-tab]");
            if (!trigger || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            const tabName = trigger.dataset.expertPublicOpenTab;
            if (!TAB_NAMES.includes(tabName)) return;
            const url = new URL(trigger.href, window.location.href);
            // Other profiles and shelf pages must keep their native navigation.
            if (url.origin !== window.location.origin || url.pathname !== window.location.pathname || url.search !== window.location.search || trigger.hasAttribute("download") || (trigger.target && trigger.target !== "_self")) return;
            event.preventDefault();
            setActiveTab(tabName);
            const hash = url.hash;
            const target = (hash.startsWith("#leader-") && document.getElementById(hash.slice(1))) || root.querySelector((TAB_PANELS[tabName] || [])[0]);
            if (target?.matches("details.expert-leader-award")) target.open = true;
            if (hash) window.history.replaceState(null, "", hash);
            target?.scrollIntoView({ block: "start", behavior: "auto" });
            target?.focus({ preventScroll: true });
        });

        const openHashTarget = () => {
            const hash = window.location.hash.slice(1);
            const target = hash.startsWith("leader-") && document.getElementById(hash);
            setActiveTab(hash.startsWith("leader-") ? "achievements" : TAB_NAMES.includes(hash) ? hash : root.dataset.activeTab || "predictions");
            if (target) {
                if (target.matches("details.expert-leader-award")) target.open = true;
                target.scrollIntoView({ block: "start", behavior: "auto" });
                target.focus({ preventScroll: true });
            }
        };
        window.addEventListener("hashchange", openHashTarget);
        openHashTarget();
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
