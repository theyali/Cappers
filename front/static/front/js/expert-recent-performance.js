(() => {
    const root = document.querySelector("[data-expert-performance]");
    const dataNode = document.getElementById("expert-recent-performance-data");
    if (!root || !dataNode) return;

    const statsAnchor = document.querySelector(".expert-public-stats");
    if (statsAnchor && statsAnchor.parentElement) {
        statsAnchor.insertAdjacentElement("afterend", root);
    }

    let windows = {};
    try {
        windows = JSON.parse(dataNode.textContent || "{}");
    } catch (error) {
        return;
    }

    const select = root.querySelector("[data-expert-performance-range]");
    const caption = root.querySelector("[data-performance-caption]");

    const pluralizePredictions = (count) => {
        const mod10 = count % 10;
        const mod100 = count % 100;
        if (mod10 === 1 && mod100 !== 11) return "прогноз";
        if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "прогноза";
        return "прогнозов";
    };

    const render = (limit) => {
        const data = windows[String(limit)] || windows["10"];
        if (!data) return;

        root.querySelectorAll("[data-performance-state]").forEach((card) => {
            const state = card.dataset.performanceState;
            const item = data[state] || { count: 0, percent: 0 };
            const percent = Math.max(0, Math.min(100, Number(item.percent || 0)));
            const count = Math.max(0, Number(item.count || 0));

            card.querySelector("[data-performance-ring]")?.setAttribute(
                "stroke-dasharray",
                `${percent} 100`,
            );
            const percentNode = card.querySelector("[data-performance-percent]");
            const countNode = card.querySelector("[data-performance-count]");
            if (percentNode) percentNode.textContent = `${percent}%`;
            if (countNode) countNode.textContent = `${count} ${pluralizePredictions(count)}`;
        });

        const total = Math.max(0, Number(data.total || 0));
        if (caption) {
            caption.textContent = total
                ? `По ${total} рассчитанным ${pluralizePredictions(total)}`
                : "Пока нет рассчитанных прогнозов";
        }
    };

    select?.addEventListener("change", () => render(select.value));
    render(select?.value || "10");
})();
