(() => {
    const TAB_LIST_SELECTOR = ".matches-mobile-scope-panel .matches-tabs";
    const ACTIVE_SELECTOR = ".is-active, [aria-current='page'], [aria-selected='true']";
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let scheduled = 0;

    const centerActiveTab = (tabs, behavior = "smooth") => {
        if (!tabs || tabs.scrollWidth <= tabs.clientWidth + 2) return;

        const active = tabs.querySelector(ACTIVE_SELECTOR);
        if (!active) return;

        const maxScroll = tabs.scrollWidth - tabs.clientWidth;
        const target = active.offsetLeft - (tabs.clientWidth - active.offsetWidth) / 2;
        const nextLeft = Math.max(0, Math.min(maxScroll, target));

        tabs.scrollTo({
            left: nextLeft,
            behavior: prefersReducedMotion.matches ? "auto" : behavior,
        });
    };

    const centerAllActiveTabs = (behavior = "smooth") => {
        document.querySelectorAll(TAB_LIST_SELECTOR).forEach((tabs) => {
            centerActiveTab(tabs, behavior);
        });
    };

    const scheduleCentering = (behavior = "smooth") => {
        window.cancelAnimationFrame(scheduled);
        scheduled = window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => centerAllActiveTabs(behavior));
        });
    };

    const init = () => {
        scheduleCentering("smooth");

        document.addEventListener("click", (event) => {
            if (event.target.closest(`${TAB_LIST_SELECTOR} a`)) {
                window.setTimeout(() => scheduleCentering("smooth"), 0);
            }
        });

        window.addEventListener("popstate", () => scheduleCentering("smooth"));
        window.addEventListener("profile:tab-activated", () => scheduleCentering("smooth"));
        window.addEventListener("resize", () => scheduleCentering("auto"), { passive: true });
        window.addEventListener("orientationchange", () => scheduleCentering("auto"), { passive: true });

        const observer = new MutationObserver((mutations) => {
            if (mutations.some((mutation) => (
                mutation.type === "childList"
                || mutation.attributeName === "class"
                || mutation.attributeName === "aria-current"
                || mutation.attributeName === "aria-selected"
            ))) {
                scheduleCentering("smooth");
            }
        });

        document.querySelectorAll(".matches-mobile-scope-panel").forEach((panel) => {
            observer.observe(panel, {
                attributes: true,
                attributeFilter: ["class", "aria-current", "aria-selected"],
                childList: true,
                subtree: true,
            });
        });

        if (document.fonts?.ready) {
            document.fonts.ready.then(() => scheduleCentering("auto")).catch(() => {});
        }
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
