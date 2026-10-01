(() => {
    const modal = document.querySelector("[data-vip-switch-modal]");
    if (!modal) return;

    let pendingForm = null;
    const confirmButton = modal.querySelector("[data-vip-switch-confirm]");
    const title = modal.querySelector("#vip-switch-modal-title");

    const openModal = (form, planTitle) => {
        pendingForm = form;
        if (title && planTitle) title.textContent = `Перейти на ${planTitle}?`;
        modal.style.display = "grid";
        modal.setAttribute("aria-hidden", "false");
        window.requestAnimationFrame(() => confirmButton?.focus({ preventScroll: true }));
    };

    const closeModal = () => {
        pendingForm = null;
        modal.setAttribute("aria-hidden", "true");
        modal.style.display = "";
    };

    document.addEventListener("click", (event) => {
        const switchButton = event.target.closest("[data-vip-switch-open]");
        if (switchButton) {
            const form = switchButton.closest("[data-vip-plan-form]");
            if (!form) return;
            openModal(form, switchButton.dataset.vipPlanTitle || "");
            return;
        }

        if (event.target.closest("[data-vip-switch-close]")) {
            closeModal();
        }
    });

    confirmButton?.addEventListener("click", () => {
        if (!pendingForm) return;
        const modeInput = pendingForm.querySelector("[data-vip-purchase-mode]");
        if (modeInput) modeInput.value = "switch";
        pendingForm.submit();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && modal.getAttribute("aria-hidden") === "false") {
            closeModal();
        }
    });
})();
