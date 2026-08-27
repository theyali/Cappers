(() => {
    const root = document.querySelector("[data-coupon-page]");
    const nav = document.querySelector(".mobile-app-nav");
    if (!root || !nav) return;

    const form = root.querySelector("[data-coupon-form]");
    const sidebar = root.querySelector(".coupon-sidebar");
    const couponButton = nav.querySelector("[data-mobile-coupon-toggle]");
    if (!form || !sidebar || !couponButton) return;

    const mobileQuery = window.matchMedia("(max-width: 1120px)");
    const itemsRoot = root.querySelector("[data-coupon-items]");
    const coefficientNode = root.querySelector("[data-coupon-coefficient]");

    const handle = form.querySelector("[data-mobile-coupon-close]");
    const badge = couponButton.querySelector("[data-mobile-coupon-badge]");
    const tooltip = couponButton.querySelector("[data-mobile-coupon-tooltip]");
    let previousActive = nav.querySelector(".mobile-app-nav-item.is-active:not(.mobile-nav-coupon)");
    let previousCount = itemsRoot?.children.length || 0;
    let tooltipTimer = null;
    let pendingBetScrollY = null;

    const itemCount = () => itemsRoot?.children.length || 0;

    const hideTooltip = () => {
        if (tooltipTimer) {
            window.clearTimeout(tooltipTimer);
            tooltipTimer = null;
        }
        if (tooltip) tooltip.hidden = true;
    };

    const syncIndicator = () => {
        const count = itemCount();
        const coefficient = coefficientNode?.textContent?.trim() || "0.00";
        couponButton.classList.toggle("has-items", count > 0);
        if (badge) {
            badge.textContent = String(count);
            badge.hidden = count === 0;
        }
        if (tooltip) tooltip.textContent = `К = ${coefficient}`;
        if (count === 0) hideTooltip();
        couponButton.setAttribute(
            "aria-label",
            count ? `Купон: ${count} игр, общий коэффициент ${coefficient}` : "Купоны"
        );
    };

    const showTooltip = () => {
        if (!tooltip || !mobileQuery.matches || itemCount() === 0 || sidebar.classList.contains("is-mobile-coupon-open")) return;
        if (tooltipTimer) window.clearTimeout(tooltipTimer);
        tooltip.hidden = false;
        tooltipTimer = window.setTimeout(() => {
            tooltip.hidden = true;
            tooltipTimer = null;
        }, 2000);
    };

    const openSheet = () => {
        if (!mobileQuery.matches) return;
        hideTooltip();
        const currentActive = nav.querySelector(".mobile-app-nav-item.is-active:not(.mobile-nav-coupon)");
        if (currentActive) previousActive = currentActive;
        previousActive?.classList.remove("is-active");
        couponButton.classList.add("is-active");
        sidebar.classList.remove("is-collapsed");
        sidebar.classList.add("is-mobile-coupon-open");
        document.body.classList.add("mobile-coupon-sheet-open");
        couponButton.setAttribute("aria-expanded", "true");
    };

    const closeSheet = () => {
        sidebar.classList.remove("is-mobile-coupon-open");
        document.body.classList.remove("mobile-coupon-sheet-open");
        couponButton.classList.remove("is-active");
        previousActive?.classList.add("is-active");
        couponButton.setAttribute("aria-expanded", "false");
    };

    couponButton.addEventListener("click", (event) => {
        if (!mobileQuery.matches) return;
        event.preventDefault();
        if (sidebar.classList.contains("is-mobile-coupon-open")) closeSheet();
        else openSheet();
    });

    handle?.addEventListener("click", closeSheet);

    let startY = null;
    handle?.addEventListener("pointerdown", (event) => {
        startY = event.clientY;
        handle.setPointerCapture?.(event.pointerId);
    });
    handle?.addEventListener("pointerup", (event) => {
        if (startY !== null && event.clientY - startY > 42) closeSheet();
        startY = null;
    });

    document.addEventListener("pointerdown", (event) => {
        if (!mobileQuery.matches || !sidebar.classList.contains("is-mobile-coupon-open")) return;
        const target = event.target;
        if (!(target instanceof Node)) return;
        if (sidebar.contains(target) || couponButton.contains(target)) return;
        closeSheet();
    });

    document.addEventListener("click", (event) => {
        const betButton = event.target.closest("[data-bet-option]");
        if (!betButton || betButton.disabled || !mobileQuery.matches) return;
        pendingBetScrollY = window.scrollY;
    }, true);

    document.addEventListener("click", (event) => {
        const betButton = event.target.closest("[data-bet-option]");
        if (!betButton || betButton.disabled || !mobileQuery.matches || pendingBetScrollY === null) return;

        const stableScrollY = pendingBetScrollY;
        pendingBetScrollY = null;
        window.requestAnimationFrame(() => {
            window.scrollTo({ top: stableScrollY, left: 0, behavior: "auto" });
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && sidebar.classList.contains("is-mobile-coupon-open")) closeSheet();
    });

    const itemsObserver = new MutationObserver(() => {
        const count = itemCount();
        const oldCount = previousCount;

        syncIndicator();

        if (mobileQuery.matches && count > oldCount) {
            if (oldCount === 0 && count === 1) {
                openSheet();
            } else {
                showTooltip();
            }
        }

        previousCount = count;
    });

    if (itemsRoot) itemsObserver.observe(itemsRoot, { childList: true });

    const coefficientObserver = new MutationObserver(() => {
        syncIndicator();
    });
    if (coefficientNode) {
        coefficientObserver.observe(coefficientNode, {
            childList: true,
            characterData: true,
            subtree: true,
        });
    }

    const handleViewportChange = () => {
        if (!mobileQuery.matches) {
            hideTooltip();
            closeSheet();
        }
    };
    mobileQuery.addEventListener?.("change", handleViewportChange);

    syncIndicator();
})();
