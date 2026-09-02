(() => {
    if (window.CappersHelp) return;

    let activeModal = null;
    let activeTrigger = null;
    let activeRequest = null;
    const accordionAnimations = new WeakMap();

    const prefersReducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    const play = (element, keyframes, options) => {
        if (!element || typeof element.animate !== "function" || prefersReducedMotion()) return null;
        const animation = element.animate(keyframes, options);
        animation.finished.catch(() => {}).finally(() => animation.cancel());
        return animation;
    };

    const showModal = (modal) => {
        if (!modal) return;
        modal.setAttribute("aria-hidden", "false");
        modal.style.display = "grid";

        const backdrop = modal.querySelector(".profile-email-modal-backdrop");
        const dialog = modal.querySelector("[data-site-help-dialog]") || modal.querySelector(".profile-email-modal-card");

        play(
            backdrop,
            [{ opacity: 0 }, { opacity: 1 }],
            { duration: 190, easing: "ease-out", fill: "both" },
        );
        play(
            dialog,
            [
                { opacity: 0, transform: "translateY(18px) scale(.975)" },
                { opacity: 1, transform: "translateY(0) scale(1)" },
            ],
            { duration: 280, easing: "cubic-bezier(.2,.8,.2,1)", fill: "both" },
        );
    };

    const hideModal = async (modal) => {
        if (!modal || modal.getAttribute("aria-hidden") === "true") return;

        const backdrop = modal.querySelector(".profile-email-modal-backdrop");
        const dialog = modal.querySelector("[data-site-help-dialog]") || modal.querySelector(".profile-email-modal-card");

        if (!prefersReducedMotion() && typeof dialog?.animate === "function") {
            const backdropAnimation = backdrop?.animate(
                [{ opacity: 1 }, { opacity: 0 }],
                { duration: 150, easing: "ease-in", fill: "both" },
            );
            const dialogAnimation = dialog.animate(
                [
                    { opacity: 1, transform: "translateY(0) scale(1)" },
                    { opacity: 0, transform: "translateY(12px) scale(.985)" },
                ],
                { duration: 190, easing: "cubic-bezier(.4,0,1,1)", fill: "both" },
            );
            await Promise.allSettled([
                backdropAnimation?.finished,
                dialogAnimation.finished,
            ].filter(Boolean));
            backdropAnimation?.cancel();
            dialogAnimation.cancel();
        }

        modal.setAttribute("aria-hidden", "true");
        modal.style.display = "";
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

    const close = async (modal = activeModal) => {
        if (!modal) return;

        if (activeRequest) {
            activeRequest.abort();
            activeRequest = null;
        }

        const trigger = activeTrigger;
        if (modal === activeModal) {
            activeModal = null;
            activeTrigger = null;
        }

        await hideModal(modal);
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

    const cleanupAccordionBody = (body) => {
        body.style.removeProperty("height");
        body.style.removeProperty("overflow");
        body.style.removeProperty("opacity");
        body.style.removeProperty("transform");
    };

    const setAccordion = (details, shouldOpen) => {
        if (!details) return;
        const body = details.querySelector("[data-site-help-accordion-body]");
        if (!body) {
            details.open = shouldOpen;
            return;
        }

        const previous = accordionAnimations.get(details);
        if (previous) previous.cancel();

        details.dataset.helpAccordionOpen = shouldOpen ? "true" : "false";

        const wasRendered = details.open;
        const startHeight = wasRendered ? body.getBoundingClientRect().height : 0;
        if (shouldOpen) details.open = true;
        const endHeight = shouldOpen ? body.scrollHeight : 0;

        if (prefersReducedMotion() || typeof body.animate !== "function") {
            details.open = shouldOpen;
            cleanupAccordionBody(body);
            return;
        }

        body.style.overflow = "hidden";
        const animation = body.animate(
            [
                {
                    height: `${startHeight}px`,
                    opacity: shouldOpen && startHeight === 0 ? 0 : 1,
                    transform: shouldOpen && startHeight === 0 ? "translateY(-6px)" : "translateY(0)",
                },
                {
                    height: `${endHeight}px`,
                    opacity: shouldOpen ? 1 : 0,
                    transform: shouldOpen ? "translateY(0)" : "translateY(-6px)",
                },
            ],
            {
                duration: 260,
                easing: "cubic-bezier(.2,.8,.2,1)",
                fill: "both",
            },
        );

        accordionAnimations.set(details, animation);

        animation.finished.then(() => {
            if (accordionAnimations.get(details) !== animation) return;
            accordionAnimations.delete(details);
            details.open = shouldOpen;
            cleanupAccordionBody(body);
            animation.cancel();
        }).catch(() => {});
    };

    const toggleAccordion = (summary) => {
        const details = summary?.closest("[data-site-help-accordion]");
        if (!details) return;

        const currentState = details.dataset.helpAccordionOpen;
        const isOpen = currentState === undefined ? details.open : currentState === "true";
        const shouldOpen = !isOpen;

        if (shouldOpen) {
            const group = details.closest("[data-site-help-accordions]");
            group?.querySelectorAll("[data-site-help-accordion]").forEach((item) => {
                if (item !== details) {
                    const itemState = item.dataset.helpAccordionOpen;
                    const itemOpen = itemState === undefined ? item.open : itemState === "true";
                    if (itemOpen) setAccordion(item, false);
                }
            });
        }

        setAccordion(details, shouldOpen);
    };

    const open = async (trigger) => {
        const modalId = trigger.dataset.helpTarget;
        const url = trigger.dataset.helpUrl;
        const modal = modalId ? document.getElementById(modalId) : null;
        if (!modal || !url) return;

        if (activeModal && activeModal !== modal) await close(activeModal);

        activeModal = modal;
        activeTrigger = trigger;
        showModal(modal);

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
            content.querySelectorAll("[data-site-help-accordion]").forEach((details) => {
                details.dataset.helpAccordionOpen = details.open ? "true" : "false";
            });
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
        const accordionSummary = event.target.closest("[data-site-help-accordion-summary]");
        if (accordionSummary) {
            event.preventDefault();
            toggleAccordion(accordionSummary);
            return;
        }

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
