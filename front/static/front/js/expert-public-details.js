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
        if (!dialog) return;
        // Fixed dialogs must not be clipped by a profile/content stacking context.
        document.body.appendChild(modal);
        const closeButtons = Array.from(modal.querySelectorAll("[data-expert-public-details-close]"));
        let lastFocused = null;
        let closeTimer = null;
        let isOpen = false;
        let background = [];

        const isolateBackground = () => {
            if (background.length) return;
            background = Array.from(document.body.children)
                .filter((element) => element instanceof HTMLElement && element !== modal)
                .map((element) => ({ element, wasInert: element.inert }));
            background.forEach(({ element }) => { element.inert = true; });
        };

        const restoreBackground = () => {
            background.forEach(({ element, wasInert }) => { element.inert = wasInert; });
            background = [];
        };

        const focusDialog = () => {
            window.requestAnimationFrame(() => {
                if (!isOpen) return;
                const target = dialog.querySelector("button[data-expert-public-details-close]") || dialog;
                target.focus({ preventScroll: true });
            });
        };

        const open = (event) => {
            event?.preventDefault();
            if (isOpen) return;
            if (closeTimer) {
                window.clearTimeout(closeTimer);
                closeTimer = null;
            }
            if (!modal.classList.contains("is-open")) {
                lastFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
                const body = dialog.querySelector(".expert-public-details-body");
                if (body) body.scrollTop = 0;
            }
            isOpen = true;
            isolateBackground();
            modal.classList.add("is-open");
            modal.setAttribute("aria-hidden", "false");
            document.documentElement.classList.add("expert-public-details-open");
            document.body.classList.add("expert-public-details-open");

            window.requestAnimationFrame(() => {
                if (!isOpen) return;
                modal.classList.add("is-visible");
                focusDialog();
            });
        };

        const close = (event) => {
            event?.preventDefault();
            if (!isOpen) return;

            isOpen = false;
            modal.classList.remove("is-visible");

            closeTimer = window.setTimeout(() => {
                modal.classList.remove("is-open");
                closeTimer = null;
                restoreBackground();
                document.documentElement.classList.remove("expert-public-details-open");
                document.body.classList.remove("expert-public-details-open");
                if (lastFocused?.isConnected) lastFocused.focus({ preventScroll: true });
                modal.setAttribute("aria-hidden", "true");
            }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : transitionMs);
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
            if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
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
