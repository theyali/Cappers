(() => {
    const modal = document.getElementById("expert-paid-subscribe-modal");
    if (!modal) return;
    const content = modal.querySelector("[data-subscription-content]");
    const card = modal.querySelector("[data-expert-public-details-dialog]");
    const controller = () => window.CappersPublicModals?.get("paid-subscribe");
    let loadRequest = null;
    let busy = false;

    const showPurchaseResult = (html) => {
        content.innerHTML = html;
        card.scrollTop = 0;
        card.setAttribute("aria-label", "Прогноз открыт");
        content.querySelector("[data-purchase-success]")?.focus({ preventScroll: true });
    };

    const bindError = (form) => {
        const error = form.querySelector("[data-checkout-error]");
        return (message) => {
            error.textContent = message;
            error.hidden = !message;
            if (message) error.focus();
        };
    };

    const submitCheckout = async (form, showError) => {
        if (busy) return;
        const method = form.querySelector("[name='payment_method']:checked:not(:disabled)")?.value;
        if (!method) return showError("Выберите доступный способ оплаты.");
        const pay = form.querySelector("[data-checkout-pay]");
        const body = new FormData(form);
        body.delete("payment_method");
        body.set("provider", method);
        const controls = new Map([...form.querySelectorAll("input, button")].map((control) => [control, control.disabled]));
        busy = true;
        controls.forEach((_disabled, control) => { control.disabled = true; });
        form.setAttribute("aria-busy", "true");
        showError("");
        try {
            const response = await fetch(method === "balance" ? form.action : pay.dataset.providerAction, {
                method: "POST", body, credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (response.redirected) {
                window.location.assign(response.url);
                return;
            }
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.ok) throw new Error(result.message || "Не удалось оплатить покупку. Попробуйте ещё раз.");
            if (method === "balance" && result.html) {
                showPurchaseResult(result.html);
            } else if (method === "telegram_stars" && window.Telegram?.WebApp?.openInvoice) {
                await new Promise((resolve) => window.Telegram.WebApp.openInvoice(result.checkout_url, (status) => {
                    if (status === "paid" || status === "pending") window.location.assign(result.return_url);
                    else if (status === "failed") showError("Оплата не прошла. Попробуйте ещё раз.");
                    resolve();
                }));
            } else {
                window.location.assign(result.checkout_url || result.return_url);
            }
        } catch (failure) {
            showError(failure.message || "Проверьте подключение и попробуйте ещё раз.");
        } finally {
            busy = false;
            controls.forEach((disabled, control) => { control.disabled = disabled; });
            form.removeAttribute("aria-busy");
        }
    };

    const bindCouponCheckout = () => {
        const form = content.querySelector("[data-single-coupon-form]");
        if (!form) return;
        const showError = bindError(form);
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            submitCheckout(form, showError);
        });
    };

    const bindCheckout = () => {
        const form = content.querySelector("[data-subscription-form]");
        if (!form) return;
        let currentStep = 1;
        const plans = JSON.parse(form.querySelector("#subscription-choices").textContent);
        const pay = form.querySelector("[data-checkout-pay]");
        const methodInputs = [...form.querySelectorAll("[name='payment_method']")];
        const selectedPlan = () => plans.find((plan) => plan.id === form.querySelector("[name='plan_id']:checked")?.value);
        const showError = bindError(form);
        const update = () => {
            const plan = selectedPlan();
            if (!plan) return;
            form.querySelectorAll("[data-subscription-period]").forEach((node) => { node.textContent = plan.label; });
            form.querySelectorAll("[data-subscription-price]").forEach((node) => { node.textContent = `${plan.price_label} ₽`; });
            form.querySelector("[data-subscription-expiry]").textContent = plan.expires_label;
            methodInputs.forEach((input) => {
                input.disabled = input.value === "balance" ? !plan.can_afford : !plan.providers.includes(input.value);
                const provider = input.closest("[data-subscription-provider]");
                if (provider) provider.hidden = input.disabled;
                if (input.disabled) input.checked = false;
            });
            if (!methodInputs.some((input) => input.checked)) {
                const first = methodInputs.find((input) => !input.disabled);
                if (first) first.checked = true;
            }
            const insufficient = form.querySelector("[data-subscription-insufficient]");
            if (insufficient) insufficient.hidden = plan.can_afford;
            const unavailable = !methodInputs.some((input) => !input.disabled);
            form.querySelector("[data-subscription-unavailable]").hidden = !unavailable;
            pay.disabled = unavailable;
            pay.textContent = `Оплатить ${plan.price_label} ₽`;
        };
        const setStep = (step) => {
            currentStep = step;
            form.querySelectorAll("[data-subscription-step]").forEach((node) => { node.hidden = node.dataset.subscriptionStep !== String(step); });
            card.classList.toggle("is-payment", step === 2);
            form.querySelector("[data-subscription-back]").hidden = step === 1;
            form.querySelector("[data-subscription-step-label]").textContent = step === 1 ? "ШАГ 1 ИЗ 2 · ВЫБОР ТАРИФА" : "ШАГ 2 ИЗ 2 · ОПЛАТА";
            form.querySelector("[data-subscription-title]").textContent = step === 1 ? "Подписка на прогнозы" : "Оплата подписки";
            form.querySelector("[data-subscription-intro]").hidden = step === 2;
            showError("");
            card.scrollTop = 0;
            const heading = form.querySelector("[data-subscription-title]");
            heading.tabIndex = -1;
            heading.focus({ preventScroll: true });
        };
        form.addEventListener("change", update);
        form.querySelector("[data-subscription-continue]").addEventListener("click", () => setStep(2));
        form.querySelector("[data-subscription-back]").addEventListener("click", () => setStep(1));
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            if (busy) return;
            if (currentStep === 1) return setStep(2);
            submitCheckout(form, showError);
        });
        update();
    };

    const openCheckout = async (url, trigger) => {
        if (busy) return;
        loadRequest?.abort();
        const request = new AbortController();
        loadRequest = request;
        trigger?.setAttribute("aria-busy", "true");
        // Both purchases share one dialog, focus trap and loading state.
        const isCoupon = /\/coupons\/\d+\/checkout\//.test(new URL(url, window.location.href).pathname);
        card.classList.remove("is-payment");
        card.scrollTop = 0;
        card.classList.toggle("is-single-purchase", isCoupon);
        card.setAttribute("aria-label", isCoupon ? "Покупка прогноза" : "Подписка на прогнозы");
        const status = document.createElement("p");
        status.className = "subscription-loading";
        status.setAttribute("role", "status");
        status.textContent = isCoupon ? "Загружаем купон…" : "Загружаем тарифы…";
        content.replaceChildren(status);
        controller()?.open(null, trigger);
        try {
            const response = await fetch(url, { credentials: "same-origin", signal: request.signal, headers: { "X-Requested-With": "XMLHttpRequest" } });
            if (request.signal.aborted) return;
            if (response.redirected) {
                window.location.assign(response.url);
                return;
            }
            if (!response.ok) throw new Error("Не удалось загрузить покупку. Попробуйте ещё раз.");
            const html = await response.text();
            if (request.signal.aborted) return;
            content.innerHTML = html;
            if (isCoupon) bindCouponCheckout();
            else bindCheckout();
            content.querySelector("[data-purchase-success]")?.focus({ preventScroll: true });
        } catch (error) {
            if (error.name === "AbortError") return;
            status.textContent = error.message;
            const retry = document.createElement("button");
            retry.type = "button";
            retry.className = "subscription-primary";
            retry.textContent = "Попробовать снова";
            retry.addEventListener("click", () => openCheckout(url, trigger));
            content.replaceChildren(status, retry);
        } finally {
            trigger?.removeAttribute("aria-busy");
        }
    };
    document.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const trigger = event.target.closest?.("a[href], [data-subscription-url]");
        if (!trigger || trigger.target === "_blank") return;
        const url = new URL(trigger.dataset.subscriptionUrl || trigger.href, window.location.href);
        if (url.origin !== window.location.origin || !/^\/cabinet\/(?:experts\/\d+\/paid-subscribe|coupons\/\d+\/checkout)\/$/.test(url.pathname)) return;
        event.preventDefault();
        openCheckout(url.href, trigger);
    }, true);
    const current = new URL(window.location.href);
    const analystId = current.searchParams.get("paid_subscribe");
    const couponId = current.searchParams.get("buy_coupon");
    const planId = current.searchParams.get("paid_plan");
    const targetId = couponId || analystId;
    if (targetId && /^\d+$/.test(targetId)) {
        current.searchParams.delete("paid_subscribe");
        current.searchParams.delete("buy_coupon");
        current.searchParams.delete("paid_plan");
        window.history.replaceState(window.history.state, "", current);
        const path = couponId ? `/cabinet/coupons/${couponId}/checkout/` : `/cabinet/experts/${analystId}/paid-subscribe/`;
        const url = new URL(path, current);
        url.searchParams.set("next", current.pathname + current.search + current.hash);
        if (!couponId && planId && /^\d+$/.test(planId)) url.searchParams.set("plan_id", planId);
        openCheckout(url.href);
    }
})();
