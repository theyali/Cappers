(() => {
    document.querySelectorAll("[data-expert-tariff-picker]").forEach((picker) => {
        const plans = JSON.parse(picker.querySelector("#expert-tariff-plans").textContent);
        picker.addEventListener("change", (event) => {
            if (!event.target.matches("[name='expert_tariff_plan']")) return;
            const plan = plans.find((choice) => choice.id === event.target.value);
            if (!plan) return;
            picker.querySelector("[data-tariff-price]").textContent = `${plan.price_label} ₽`;
            picker.querySelector("[data-tariff-period]").textContent = plan.label;
            picker.querySelector("[data-tariff-daily]").textContent = plan.daily_label;
            const discount = picker.querySelector("[data-tariff-discount]");
            discount.textContent = `−${plan.discount}% к цене дня`;
            discount.hidden = !plan.discount;
            picker.querySelector("[data-tariff-checkout]").href = plan.action_url;
            picker.querySelector("[data-tariff-action]").textContent = plan.rail_label;
            picker.querySelector("[data-tariff-mobile-action]").textContent = plan.mobile_label;
        });
    });
})();
