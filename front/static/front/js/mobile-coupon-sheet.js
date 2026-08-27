(() => {
    const root = document.querySelector("[data-coupon-page]");
    const nav = document.querySelector(".mobile-app-nav");
    if (!root || !nav) return;

    const form = root.querySelector("[data-coupon-form]");
    const sidebar = root.querySelector(".coupon-sidebar");
    if (!form || !sidebar) return;

    const mobileQuery = window.matchMedia("(max-width: 1120px)");
    const itemsRoot = root.querySelector("[data-coupon-items]");
    const coefficientNode = root.querySelector("[data-coupon-coefficient]");

    const pageItems = Array.from(nav.querySelectorAll(":scope > .mobile-app-nav-item"));
    const iconClasses = ["mobile-nav-home", "mobile-nav-matches", "mobile-nav-articles", "mobile-nav-my", "mobile-nav-profile"];
    pageItems.forEach((item, index) => item.classList.add(iconClasses[index] || ""));

    const couponButton = document.createElement("button");
    couponButton.type = "button";
    couponButton.className = "mobile-app-nav-item mobile-nav-coupon";
    couponButton.dataset.mobileCouponToggle = "";
    couponButton.setAttribute("aria-controls", "mobile-coupon-sheet");
    couponButton.setAttribute("aria-expanded", "false");
    couponButton.innerHTML = `
        <span class="mobile-coupon-nav-tooltip" data-mobile-coupon-tooltip hidden></span>
        <span class="mobile-app-nav-icon" aria-hidden="true"></span>
        <span class="mobile-coupon-nav-badge" data-mobile-coupon-badge hidden>0</span>
        <span class="mobile-app-nav-label">Купоны</span>
    `;

    const insertBefore = pageItems[3] || pageItems[pageItems.length - 1] || null;
    nav.insertBefore(couponButton, insertBefore);

    sidebar.id = "mobile-coupon-sheet";
    sidebar.classList.add("coupon-sidebar-editor");

    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = "mobile-coupon-sheet-handle";
    handle.dataset.mobileCouponClose = "";
    handle.setAttribute("aria-label", "Закрыть купон");
    form.prepend(handle);

    const badge = couponButton.querySelector("[data-mobile-coupon-badge]");
    const tooltip = couponButton.querySelector("[data-mobile-coupon-tooltip]");
    let previousActive = nav.querySelector(".mobile-app-nav-item.is-active:not(.mobile-nav-coupon)");

    const itemCount = () => itemsRoot?.children.length || 0;

    const syncIndicator = () => {
        const count = itemCount();
        const coefficient = coefficientNode?.textContent?.trim() || "0.00";
        couponButton.classList.toggle("has-items", count > 0);
        badge.textContent = String(count);
        badge.hidden = count === 0;
        tooltip.textContent = `К = ${coefficient}`;
        tooltip.hidden = count === 0;
        couponButton.setAttribute("aria-label", count ? `Купон: ${count} игр, общий коэффициент ${coefficient}` : "Купоны");
    };

    const openSheet = () => {
        if (!mobileQuery.matches) return;
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

    couponButton.addEventListener("click", () => {
        if (sidebar.classList.contains("is-mobile-coupon-open")) closeSheet();
        else openSheet();
    });

    handle.addEventListener("click", closeSheet);

    let startY = null;
    handle.addEventListener("pointerdown", (event) => {
        startY = event.clientY;
        handle.setPointerCapture?.(event.pointerId);
    });
    handle.addEventListener("pointerup", (event) => {
        if (startY !== null && event.clientY - startY > 42) closeSheet();
        startY = null;
    });

    document.addEventListener("click", (event) => {
        const betButton = event.target.closest("[data-bet-option]");
        if (!betButton || betButton.disabled || !mobileQuery.matches) return;
        window.requestAnimationFrame(() => {
            syncIndicator();
            if (itemCount() > 0) openSheet();
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && sidebar.classList.contains("is-mobile-coupon-open")) closeSheet();
    });

    const observer = new MutationObserver(syncIndicator);
    if (itemsRoot) observer.observe(itemsRoot, { childList: true });
    if (coefficientNode) observer.observe(coefficientNode, { childList: true, characterData: true, subtree: true });

    const handleViewportChange = () => {
        if (!mobileQuery.matches) closeSheet();
    };
    mobileQuery.addEventListener?.("change", handleViewportChange);

    syncIndicator();
})();
