(() => {
    if (window.CappersHelp) return;

    let activeModal = null;
    let activeTrigger = null;
    let activeRequest = null;

    const setModalVisible = (modal, visible) => {
        if (!modal) return;
        modal.setAttribute("aria-hidden", visible ? "false" : "true");
        modal.style.display = visible ? "grid" : "";
    };

    const positionTrigger = (trigger) => {
        if (!trigger || trigger.dataset.helpPosition !== "top-right") return;

        const positionTarget = trigger.closest("[data-site-help-position-target]") || trigger;
        const anchor = positionTarget.closest("[data-site-help-anchor]") || positionTarget.closest(".tournaments-hero");
        if (!anchor) return;

        positionTarget.style.position = "absolute";
        positionTarget.style.top = "18px";
        positionTarget.style.right = "18px";
        positionTarget.style.zIndex = "4";
        positionTarget.style.width = "auto";
        positionTarget.style.minWidth = "0";
        positionTarget.style.gridColumn = "auto";
    };

    const positionTriggers = () => {
        document.querySelectorAll("[data-site-help-trigger]").forEach(positionTrigger);
    };

    const close = (modal = activeModal) => {
        if (!modal) return;
        setModalVisible(modal, false);

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
        content.replaceChildren();
        const state = document.createElement("div");
        state.className = "profile-empty-state";
        const text = document.createElement("p");
        text.textContent = message;
        state.appendChild(text);
        content.appendChild(state);
    };

    const open = async (trigger) => {
        const modalId = trigger.dataset.helpTarget;
        const url = trigger.dataset.helpUrl;
        const modal = modalId ? document.getElementById(modalId) : null;
        if (!modal || !url) return;

        if (activeModal && activeModal !== modal) close(activeModal);

        activeModal = modal;
        activeTrigger = trigger;
        setModalVisible(modal, true);

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

    positionTriggers();
    window.CappersHelp = { open, close, positionTriggers };
})();