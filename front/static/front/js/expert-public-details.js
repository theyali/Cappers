(() => {
    const transitionMs = 220;

    const focusableSelector = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    const initModal = (modal, triggers) => {
        if (!modal || !triggers.length) return;

        const dialog = modal.querySelector("[data-expert-public-details-dialog]");
        const closeButtons = Array.from(modal.querySelectorAll("[data-expert-public-details-close]"));
        let lastFocused = null;
        let closeTimer = null;

        const focusDialog = () => {
            window.requestAnimationFrame(() => {
                dialog?.focus({ preventScroll: true });
            });
        };

        const open = (event) => {
            event?.preventDefault();
            if (closeTimer) {
                window.clearTimeout(closeTimer);
                closeTimer = null;
            }
            if (modal.classList.contains("is-open")) return;

            lastFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            modal.classList.add("is-open");
            modal.setAttribute("aria-hidden", "false");
            document.body.classList.add("expert-public-details-open");

            window.requestAnimationFrame(() => {
                modal.classList.add("is-visible");
                focusDialog();
            });
        };

        const close = (event) => {
            event?.preventDefault();
            if (!modal.classList.contains("is-open")) return;

            modal.classList.remove("is-visible");
            modal.setAttribute("aria-hidden", "true");
            document.body.classList.remove("expert-public-details-open");

            closeTimer = window.setTimeout(() => {
                modal.classList.remove("is-open");
                closeTimer = null;
                lastFocused?.focus({ preventScroll: true });
            }, transitionMs);
        };

        const trapFocus = (event) => {
            if (event.key !== "Tab" || !modal.classList.contains("is-open") || !dialog) return;
            const focusable = Array.from(dialog.querySelectorAll(focusableSelector)).filter((item) => {
                return item instanceof HTMLElement && !item.hidden && item.offsetParent !== null;
            });
            if (!focusable.length) {
                event.preventDefault();
                dialog.focus();
                return;
            }

            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };

        triggers.forEach((trigger) => {
            trigger.addEventListener("click", open);
        });
        closeButtons.forEach((button) => {
            button.addEventListener("click", close);
        });

        document.addEventListener("keydown", (event) => {
            if (!modal.classList.contains("is-open")) return;
            if (event.key === "Escape") {
                event.preventDefault();
                close();
                return;
            }
            trapFocus(event);
        });
    };

    document.querySelectorAll("[data-expert-public-modal]").forEach((modal) => {
        const modalKey = modal.dataset.expertPublicModal;
        const triggers = Array.from(
            document.querySelectorAll(`[data-expert-public-modal-open="${modalKey}"]`)
        );
        initModal(modal, triggers);
    });
})();
