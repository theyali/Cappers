(() => {
    const root = document.querySelector("[data-expert-sport-profit]");
    const dataNode = document.getElementById("expert-sport-profit-data");
    if (!root || !dataNode) return;

    let periods = {};
    try {
        periods = JSON.parse(dataNode.textContent || "{}");
    } catch (error) {
        console.error("Не удалось прочитать статистику по видам спорта.", error);
        return;
    }

    const filter = root.querySelector(".expert-sport-profit-filter");
    const toggle = root.querySelector("[data-sport-profit-toggle]");
    const label = root.querySelector("[data-sport-profit-label]");
    const menu = root.querySelector("[data-sport-profit-menu]");
    const periodButtons = Array.from(root.querySelectorAll("[data-sport-profit-period]"));
    const cards = Array.from(root.querySelectorAll("[data-sport-profit-card]"));

    const closeMenu = () => {
        if (!filter || !toggle || !menu) return;
        filter.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        menu.hidden = true;
    };

    const openMenu = () => {
        if (!filter || !toggle || !menu) return;
        filter.classList.add("is-open");
        toggle.setAttribute("aria-expanded", "true");
        menu.hidden = false;
    };

    const setWidth = (element, value) => {
        if (!element) return;
        const numeric = Math.max(0, Math.min(100, Number(value) || 0));
        element.style.width = `${numeric}%`;
    };

    const renderPeriod = (key) => {
        const period = periods[key];
        if (!period) return;
        const rows = new Map((period.rows || []).map((row) => [String(row.code), row]));

        cards.forEach((card) => {
            const row = rows.get(card.dataset.sportProfitCard || "");
            card.hidden = !row;
            if (!row) return;

            const name = card.querySelector("[data-sport-name]");
            const predictions = card.querySelector("[data-sport-predictions]");
            const profit = card.querySelector("[data-sport-profit]");
            const roi = card.querySelector("[data-sport-roi]");

            if (name) name.textContent = row.name || "Спорт";
            if (predictions) predictions.textContent = row.predictions_text || "0 прогнозов";
            if (profit) profit.textContent = row.profit_display || "0.0%";
            if (roi) roi.textContent = row.roi_display || "0.0%";

            setWidth(card.querySelector("[data-sport-win-bar]"), row.win_percent);
            setWidth(card.querySelector("[data-sport-loss-bar]"), row.loss_percent);
            setWidth(card.querySelector("[data-sport-refund-bar]"), row.refund_percent);
        });

        if (label) label.textContent = period.label || "все время";
        periodButtons.forEach((button) => {
            button.classList.toggle("is-active", button.dataset.sportProfitPeriod === key);
        });
        closeMenu();
    };

    toggle?.addEventListener("click", (event) => {
        event.stopPropagation();
        if (menu?.hidden) openMenu();
        else closeMenu();
    });

    periodButtons.forEach((button) => {
        button.addEventListener("click", () => renderPeriod(button.dataset.sportProfitPeriod || "all"));
    });

    document.addEventListener("click", (event) => {
        if (!filter?.contains(event.target)) closeMenu();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeMenu();
    });
})();
