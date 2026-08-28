(() => {
    const MIN_STAKE = 100;
    const MAX_STAKE = 1000000;
    const MIN_COEFFICIENT = 1.01;

    const root = document.querySelector("[data-coupon-page]");
    if (!root) return;

    const form = root.querySelector("[data-coupon-form]");
    const stakeInput = root.querySelector("[data-coupon-stake]");
    const submitButton = root.querySelector("[data-coupon-submit]");
    const noteNode = root.querySelector("[data-coupon-note]");
    let lastConstraintMessage = "";

    const toNumber = (value) => {
        const parsed = Number.parseFloat(String(value ?? "").replace(",", "."));
        return Number.isFinite(parsed) ? parsed : null;
    };

    const rubles = (value) => new Intl.NumberFormat("ru-RU", {
        maximumFractionDigits: 0,
    }).format(value);

    const stakeError = () => {
        if (!stakeInput || !stakeInput.value.trim()) return "";
        const value = toNumber(stakeInput.value);
        if (value === null) return "Укажите корректную сумму в рублях.";
        if (value < MIN_STAKE) return `Минимальная сумма прогноза — ${rubles(MIN_STAKE)} ₽.`;
        if (value > MAX_STAKE) return `Максимальная сумма прогноза — ${rubles(MAX_STAKE)} ₽.`;
        return "";
    };

    const updateStakeState = () => {
        if (!stakeInput) return true;
        const error = stakeError();
        stakeInput.setCustomValidity(error);
        stakeInput.closest(".coupon-field")?.classList.toggle("is-invalid", Boolean(error));
        if (error && submitButton) submitButton.disabled = true;
        return !error;
    };

    const showStakeError = () => {
        const error = stakeError();
        if (!error || !noteNode) return;
        lastConstraintMessage = error;
        noteNode.textContent = error;
        noteNode.classList.add("is-error");
        noteNode.classList.remove("is-success");
    };

    const clearConstraintError = () => {
        if (!noteNode || !lastConstraintMessage) return;
        if (noteNode.textContent.trim() === lastConstraintMessage) {
            noteNode.textContent = "Один купон — один прогноз. Матчи внутри него являются позициями прогноза.";
            noteNode.classList.remove("is-error", "is-success");
        }
        lastConstraintMessage = "";
    };

    const enforceStakeAfterCouponState = () => {
        queueMicrotask(() => {
            if (updateStakeState()) clearConstraintError();
        });
    };

    const lockMarkup = () => {
        const lock = document.createElement("i");
        lock.className = "match-odd-lock";
        lock.setAttribute("aria-hidden", "true");
        lock.innerHTML = '<svg viewBox="0 0 24 24" fill="none"><path d="M7 10V8a5 5 0 0 1 10 0v2M6 10h12a2 2 0 0 1 2 2v7H4v-7a2 2 0 0 1 2-2Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
        return lock;
    };

    const lockInvalidOdds = (scope = document) => {
        scope.querySelectorAll("[data-coefficient]").forEach((button) => {
            const coefficient = toNumber(button.dataset.coefficient);
            if (coefficient === null || coefficient >= MIN_COEFFICIENT) return;

            button.removeAttribute("data-bet-option");
            button.disabled = true;
            button.setAttribute("aria-disabled", "true");
            button.setAttribute("title", "Коэффициент 1.00 недоступен для прогноза");
            button.classList.add("is-locked-odd");
            if (!button.querySelector(".match-odd-lock")) {
                button.prepend(lockMarkup());
            }
        });
    };

    if (stakeInput) {
        stakeInput.min = String(MIN_STAKE);
        stakeInput.max = String(MAX_STAKE);
        stakeInput.step = "1";
        stakeInput.addEventListener("input", enforceStakeAfterCouponState);
        stakeInput.addEventListener("blur", () => {
            updateStakeState();
            if (stakeError()) showStakeError();
        });
        updateStakeState();
    }

    if (form) {
        form.addEventListener("submit", (event) => {
            if (updateStakeState()) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            showStakeError();
            stakeInput?.focus();
        }, true);
    }

    document.addEventListener("click", (event) => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest("[data-coefficient]");
        if (!button) return;
        const coefficient = toNumber(button.dataset.coefficient);
        if (coefficient === null || coefficient >= MIN_COEFFICIENT) return;
        event.preventDefault();
        event.stopImmediatePropagation();
    }, true);

    document.addEventListener("matches:appended", (event) => {
        const nodes = event.detail?.nodes || [];
        if (nodes.length) {
            nodes.forEach((node) => lockInvalidOdds(node));
        } else {
            lockInvalidOdds(document);
        }
    });

    document.addEventListener("DOMContentLoaded", () => {
        lockInvalidOdds(document);
        enforceStakeAfterCouponState();
    }, { once: true });

    lockInvalidOdds(document);
})();
