(() => {
    // Phone profile: compact header once the card scrolls away, socials sheet, sport chips and feed filters.
    const root = document.querySelector("[data-expert-mobile]");
    if (!root) return;

    const card = root.querySelector("[data-expert-mobile-card]");
    const tabs = document.querySelector("[data-expert-mobile-tabs]");
    if (card && tabs && "IntersectionObserver" in window) {
        new IntersectionObserver(([entry]) => {
            tabs.classList.toggle("is-condensed", !entry.isIntersecting && entry.boundingClientRect.top < 0);
        }).observe(card);
    }

    const sheet = root.querySelector("[data-expert-socials-sheet]");
    const setSheet = (open) => {
        if (!sheet) return;
        if (open) sheet.hidden = false;
        requestAnimationFrame(() => sheet.classList.toggle("is-open", open));
        document.documentElement.classList.toggle("is-expert-socials-open", open);
        if (!open) window.setTimeout(() => { sheet.hidden = !sheet.classList.contains("is-open"); }, 220);
    };

    root.addEventListener("click", (event) => {
        if (!(event.target instanceof Element)) return;
        if (event.target.closest("[data-expert-socials-open]")) {
            setSheet(true);
        } else if (event.target.closest("[data-expert-socials-close]")) {
            setSheet(false);
        } else if (event.target.closest("[data-expert-socials-show]")) {
            root.querySelectorAll("[data-expert-socials-more]").forEach((item) => { item.hidden = false; });
            event.target.closest("[data-expert-socials-show]").remove();
        } else if (event.target.closest("[data-expert-mobile-chips-show]")) {
            root.querySelectorAll("[data-expert-mobile-chip-more]").forEach((chip) => { chip.hidden = false; });
            event.target.closest("[data-expert-mobile-chips-show]").remove();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && sheet?.classList.contains("is-open")) setSheet(false);
    });

    const feed = document.querySelector("[data-expert-mobile-feed]");
    if (!feed) return;
    const filters = Array.from(feed.querySelectorAll("[data-expert-mobile-filter]"));
    const coupons = Array.from(feed.querySelectorAll("[data-state]"));
    const empty = feed.querySelector("[data-expert-mobile-feed-empty]");
    filters.forEach((button) => {
        button.addEventListener("click", () => {
            const state = button.dataset.expertMobileFilter;
            filters.forEach((item) => {
                item.classList.toggle("is-active", item === button);
                item.setAttribute("aria-pressed", item === button ? "true" : "false");
            });
            let shown = 0;
            coupons.forEach((coupon) => {
                coupon.hidden = state !== "all" && coupon.dataset.state !== state;
                if (!coupon.hidden) shown += 1;
            });
            if (empty) empty.hidden = shown > 0;
        });
    });
})();
