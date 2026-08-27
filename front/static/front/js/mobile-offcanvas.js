(() => {
    const toggle = document.querySelector("[data-mobile-offcanvas-toggle]");
    const panel = document.querySelector("[data-mobile-offcanvas]");
    const closeButton = panel?.querySelector("[data-mobile-offcanvas-close]");
    if (!toggle || !panel || !closeButton) return;

    const mobileQuery = window.matchMedia("(max-width: 760px)");
    let previousFocus = null;

    const focusableSelector = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    const getFocusable = () => [...panel.querySelectorAll(focusableSelector)]
        .filter((node) => !node.hidden && node.offsetParent !== null);

    const setOpen = (isOpen, { restoreFocus = true } = {}) => {
        panel.classList.toggle("is-open", isOpen);
        panel.setAttribute("aria-hidden", String(!isOpen));
        toggle.setAttribute("aria-expanded", String(isOpen));
        document.body.classList.toggle("mobile-offcanvas-open", isOpen);

        if (isOpen) {
            previousFocus = document.activeElement;
            window.requestAnimationFrame(() => closeButton.focus({ preventScroll: true }));
            return;
        }

        if (restoreFocus && previousFocus instanceof HTMLElement) {
            previousFocus.focus({ preventScroll: true });
        }
        previousFocus = null;
    };

    const close = (options) => setOpen(false, options);

    toggle.addEventListener("click", () => {
        setOpen(!panel.classList.contains("is-open"));
    });

    closeButton.addEventListener("click", () => close());

    panel.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        if (link) close({ restoreFocus: false });
    });

    document.addEventListener("pointerdown", (event) => {
        if (!panel.classList.contains("is-open")) return;
        if (panel.contains(event.target) || toggle.contains(event.target)) return;
        close();
    });

    document.addEventListener("keydown", (event) => {
        if (!panel.classList.contains("is-open")) return;

        if (event.key === "Escape") {
            event.preventDefault();
            close();
            return;
        }

        if (event.key !== "Tab") return;
        const focusable = getFocusable();
        if (!focusable.length) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    const handleBreakpoint = () => {
        if (!mobileQuery.matches && panel.classList.contains("is-open")) {
            close({ restoreFocus: false });
        }
    };

    if (typeof mobileQuery.addEventListener === "function") {
        mobileQuery.addEventListener("change", handleBreakpoint);
    } else {
        mobileQuery.addListener(handleBreakpoint);
    }
})();
