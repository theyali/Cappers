(() => {
    if (window.CappersHelp) return;

    let activeModal = null;
    let activeTrigger = null;
    let activeRequest = null;

    const setHash = (modalId) => {
        if (!modalId) return;
        if (window.location.hash === `#${modalId}`) return;
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${modalId}`);
    };

    const clearHash = (modal) => {
        if (!modal || window.location.hash !== `#${modal.id}`) return;
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    };

    const close = (modal = activeModal) => {
        if (!modal) return;
        clearHash(modal);
        modal.setAttribute("aria-hidden", "true");
        if (activeRequest) {
            activeRequest.abort();
            activeRequest = null;
        }
        const trigger = activeTrigger;
        activeModal = null;
        activeTrigger = null;
        trigger?.focus({ preventScroll: true });
    };

    const showError = (content, message) => {
        content.innerHTML = `<div class="profile-empty-state"><p>${message}</p></div>`;
    };

    const open = async (trigger) => {
        const modalId = trigger.dataset.helpTarget;
        const url = trigger.dataset.helpUrl;
        const modal = modalId ? document.getElementById(modalId) : null;
        if (!modal || !url) return;

        if (activeModal && activeModal !== modal) close(activeModal);

        activeModal = modal;
        activeTrigger = trigger;
        modal.setAttribute("aria-hidden", "false");
        setHash(modal.id);

        const content = modal.querySelector("[data-site-help-content]");
        const title = modal.querySelector("[data-site-help-title]");
        if (!content) return;

        if (activeRequest) activeRequest.abort();
        const controller = new AbortController();
        activeRequest = controller;

        trigger.disabled = true;
        trigger.setAttribute("aria-busy", "true");
        window.CappersSkeleton?.loading(content);

        try {
            const response = await fetch(url, {
                method: "GET",
                headers: { "X-Requested-With": "XMLHttpRequest" },
                signal: controller.signal,
                credentials: "same-origin",
                cache: "no-store",
            });
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Не удалось загрузить справку.");
            }

            if (title && payload.title) title.textContent = payload.title;
            content.innerHTML = payload.html;
            window.CappersSkeleton?.ready(content);
            modal.querySelector("[data-site-help-close]")?.focus({ preventScroll: true });
        } catch (error) {
            if (error.name === "AbortError") return;
            showError(content, error.message || "Не удалось загрузить справку.");
            window.CappersSkeleton?.ready(content);
        } finally {
            if (activeRequest === controller) activeRequest = null;
            trigger.disabled = false;
            trigger.removeAttribute("aria-busy");
        }
    };

    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-site-help-trigger]");
        if (trigger) {
            event.preventDefault();
            open(trigger);
            return;
        }

        const closeButton = event.target.closest("[data-site-help-close]");
        if (closeButton) {
            event.preventDefault();
            close(closeButton.closest("[data-site-help-modal]"));
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && activeModal) close(activeModal);
    });

    window.addEventListener("hashchange", () => {
        if (activeModal && window.location.hash !== `#${activeModal.id}`) {
            activeModal.setAttribute("aria-hidden", "true");
            activeModal = null;
            activeTrigger = null;
        }
    });

    window.CappersHelp = { open, close };
})();
