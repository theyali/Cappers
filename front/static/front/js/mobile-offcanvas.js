(() => {
    const toggle = document.querySelector("[data-mobile-offcanvas-toggle]");
    const panel = document.querySelector("[data-mobile-offcanvas]");
    if (!toggle || !panel) return;

    const mobileQuery = window.matchMedia("(max-width: 1120px)");
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
            window.requestAnimationFrame(() => {
                getFocusable()[0]?.focus({ preventScroll: true });
            });
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

    panel.addEventListener("click", (event) => {
        if (event.target.closest("[data-mobile-offcanvas-close]")) {
            close();
            return;
        }

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

    const getCookie = (name) => {
        const cookies = document.cookie ? document.cookie.split(";") : [];
        for (const cookie of cookies) {
            const trimmed = cookie.trim();
            if (trimmed.startsWith(`${name}=`)) {
                return decodeURIComponent(trimmed.slice(name.length + 1));
            }
        }
        return "";
    };

    const syncBalanceVisibility = (hidden, visibleValue, maskedValue = "***") => {
        const displayValue = hidden ? maskedValue : visibleValue;
        document.querySelectorAll("[data-wallet-balance]").forEach((node) => {
            if (!node.dataset.walletBalanceVisible && visibleValue) {
                node.dataset.walletBalanceVisible = visibleValue;
            }
            node.textContent = displayValue;
        });

        panel.querySelectorAll("[data-balance-visibility-toggle]").forEach((button) => {
            button.classList.toggle("is-hidden", hidden);
            button.setAttribute("aria-pressed", String(hidden));
            button.setAttribute(
                "aria-label",
                hidden ? button.dataset.hiddenLabel : button.dataset.visibleLabel,
            );
        });
    };

    panel.addEventListener("click", (event) => {
        const button = event.target.closest("[data-balance-visibility-toggle]");
        if (!button || !panel.contains(button)) return;
        event.preventDefault();

        const url = button.dataset.url;
        const balanceNode = panel.querySelector("[data-wallet-balance]");
        const visibleValue = balanceNode?.dataset.walletBalanceVisible || balanceNode?.textContent || "";
        const maskedValue = balanceNode?.dataset.walletBalanceMasked || "***";
        const nextHidden = !button.classList.contains("is-hidden");

        if (!url) {
            syncBalanceVisibility(nextHidden, visibleValue, maskedValue);
            return;
        }

        button.disabled = true;
        const applyPayload = (payload) => {
            if (!payload || payload.ok === false) return;
            syncBalanceVisibility(
                Boolean(payload.hidden),
                payload.balance_display || visibleValue,
                payload.masked_display || maskedValue,
            );
        };
        const finish = () => {
            button.disabled = false;
        };

        if (window.jQuery) {
            window.jQuery.ajax({
                url,
                method: "POST",
                dataType: "json",
                data: { hidden: nextHidden ? "true" : "false" },
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest",
                },
            })
                .done(applyPayload)
                .always(finish);
            return;
        }

        fetch(url, {
            method: "POST",
            credentials: "same-origin",
            body: new URLSearchParams({ hidden: nextHidden ? "true" : "false" }),
            headers: {
                "X-CSRFToken": getCookie("csrftoken"),
                "X-Requested-With": "XMLHttpRequest",
            },
        })
            .then((response) => response.json())
            .then(applyPayload)
            .finally(finish);
    });
})();

(() => {
    const panels = document.querySelectorAll(".match-detail-main > .match-odds-panel");
    if (!panels.length) return;

    const syncLayout = (panel) => {
        const body = panel.querySelector(":scope > .match-odds-accordion-body");
        const inner = body?.querySelector(":scope > .match-odds-accordion-inner");
        if (!body || !inner) return;

        const collapsed = panel.classList.contains("is-odds-collapsed");
        panel.style.flexShrink = "0";
        inner.style.minHeight = "0";
        body.style.gridTemplateRows = collapsed ? "0fr" : "1fr";
        body.style.opacity = collapsed ? "0" : "1";
    };

    panels.forEach((panel) => {
        syncLayout(panel);
        const observer = new MutationObserver(() => syncLayout(panel));
        observer.observe(panel, {
            attributes: true,
            attributeFilter: ["class"],
        });
    });
})();
