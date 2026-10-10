(() => {
    const root = document.querySelector("[data-expert-performance]");
    const dataNode = document.getElementById("expert-recent-performance-data");
    if (!root || !dataNode) return;

    const analytics = document.querySelector(".expert-public-analytics");
    if (analytics) analytics.insertAdjacentElement("beforebegin", root);

    let windows = {};
    try {
        windows = JSON.parse(dataNode.textContent || "{}");
    } catch (error) {
        return;
    }

    const select = root.querySelector("[data-expert-performance-range]");
    const caption = root.querySelector("[data-performance-caption]");

    const render = (limit) => {
        const data = windows[String(limit)] || windows["10"];
        if (!data) return;

        root.querySelectorAll("[data-performance-state]").forEach((card) => {
            const state = card.dataset.performanceState;
            const item = data[state] || { count: 0, percent: 0 };
            const percent = Math.max(0, Math.min(100, Number(item.percent || 0)));
            const count = Math.max(0, Number(item.count || 0));

            const countNode = card.querySelector("[data-performance-count]");
            if (countNode) countNode.textContent = String(count);
            const bar = root.querySelector(`[data-performance-bar="${state}"]`);
            if (bar) {
                bar.setAttribute("width", String(percent));
                bar.setAttribute("x", String(Math.max(0, Number(item.start || 0))));
            }
        });

        const winrate = root.querySelector("[data-performance-winrate]");
        if (winrate) winrate.textContent = `${data.wins?.percent || 0}%`;
        const total = Math.max(0, Number(data.total || 0));
        if (caption) {
            caption.textContent = total
                ? `винрейт по ${total} рассчитанным`
                : "Пока нет рассчитанных прогнозов";
        }
    };

    select?.addEventListener("change", () => render(select.value));
    render(select?.value || "10");
})();
