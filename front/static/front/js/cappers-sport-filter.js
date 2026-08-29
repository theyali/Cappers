(() => {
    const grid = document.querySelector(".cappers-pro-grid");
    if (!grid) return;

    const cards = Array.from(grid.querySelectorAll(".capper-pro-card"));
    if (!cards.length) return;

    const sportLabels = new Map();
    const cardState = new Map();

    cards.forEach((card, index) => {
        const stats = new Map();
        card.querySelectorAll("[data-capper-sport-source]").forEach((node) => {
            const code = node.dataset.capperSportSource || "";
            if (!code) return;
            const stat = {
                code,
                name: node.dataset.sportName || code,
                roi: Number(node.dataset.roi || 0),
                roiDisplay: node.dataset.roiDisplay || "0.0%",
                profit: Number(node.dataset.profit || 0),
                profitDisplay: node.dataset.profitDisplay || "0.0%",
                predictions: Number(node.dataset.predictions || 0),
                predictionsText: node.dataset.predictionsText || "0 прогнозов",
            };
            stats.set(code, stat);
            if (code !== "all" && !sportLabels.has(code)) {
                sportLabels.set(code, stat.name);
            }
        });

        const roiBadge = card.querySelector(".capper-pro-roi");
        const rank = card.querySelector(".capper-pro-rank");
        cardState.set(card, {
            index,
            stats,
            roiBadge,
            rank,
            originalRoiText: roiBadge?.textContent || "",
            originalRoiTitle: roiBadge?.getAttribute("title") || "",
            originalRoiClass: roiBadge?.className || "",
            originalRank: rank?.textContent || `#${index + 1}`,
        });
    });

    if (!sportLabels.size) return;

    const knownOrder = {football: 0, hockey: 1, basketball: 2, tennis: 3};
    const sports = Array.from(sportLabels.entries()).sort((a, b) => {
        const orderA = knownOrder[a[0]] ?? 100;
        const orderB = knownOrder[b[0]] ?? 100;
        if (orderA !== orderB) return orderA - orderB;
        return a[1].localeCompare(b[1], "ru");
    });

    const filter = document.createElement("div");
    filter.className = "cappers-sport-filter";
    filter.setAttribute("aria-label", "Фильтр статистики капперов по виду спорта");
    filter.dataset.cappersSportFilter = "";

    const count = document.createElement("span");
    count.className = "cappers-sport-filter-count";

    const options = [["all", "Все виды спорта"], ...sports];
    const buttons = new Map();

    options.forEach(([code, label]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.dataset.capperSportFilter = code;
        button.classList.toggle("is-active", code === "all");
        button.setAttribute("aria-pressed", code === "all" ? "true" : "false");
        buttons.set(code, button);
        filter.appendChild(button);
    });
    filter.appendChild(count);

    const sectionHead = grid.previousElementSibling;
    if (sectionHead?.classList.contains("cappers-section-head")) {
        sectionHead.insertAdjacentElement("afterend", filter);
    } else {
        grid.insertAdjacentElement("beforebegin", filter);
    }

    const setBadgeState = (badge, roi) => {
        if (!badge) return;
        badge.classList.remove("is-positive", "is-negative", "is-neutral");
        badge.classList.add(roi > 0 ? "is-positive" : roi < 0 ? "is-negative" : "is-neutral");
    };

    const updateSportStrip = (card, stat, label) => {
        const strip = card.querySelector("[data-capper-sport-stat]");
        if (!strip) return;

        const name = strip.querySelector("[data-capper-sport-name]");
        const roi = strip.querySelector("[data-capper-sport-roi]");
        const detail = strip.querySelector("[data-capper-sport-detail]");

        if (!stat) {
            strip.classList.add("is-empty");
            if (name) name.textContent = label;
            if (roi) roi.textContent = "Нет данных";
            if (detail) detail.textContent = "Нет рассчитанных прогнозов";
            return;
        }

        strip.classList.remove("is-empty");
        if (name) name.textContent = label;
        if (roi) roi.textContent = `ROI ${stat.roi > 0 ? "+" : ""}${stat.roiDisplay}`;
        if (detail) {
            detail.textContent = `${stat.predictionsText} · Прибыль ${stat.profit > 0 ? "+" : ""}${stat.profitDisplay}`;
        }
    };

    const render = (code) => {
        const label = buttons.get(code)?.textContent || "Все виды спорта";
        const visible = [];

        cards.forEach((card) => {
            const state = cardState.get(card);
            const stat = state?.stats.get(code);
            const isAll = code === "all";
            const shouldShow = isAll || Boolean(stat);

            card.hidden = !shouldShow;
            if (!shouldShow || !state) return;

            updateSportStrip(card, state.stats.get(code === "all" ? "all" : code), label);

            if (isAll) {
                if (state.roiBadge) {
                    state.roiBadge.textContent = state.originalRoiText;
                    state.roiBadge.setAttribute("title", state.originalRoiTitle);
                    state.roiBadge.className = state.originalRoiClass;
                }
                if (state.rank) state.rank.textContent = state.originalRank;
                visible.push({card, state, stat: state.stats.get("all"), sort: state.index});
            } else {
                if (state.roiBadge && stat) {
                    state.roiBadge.textContent = `ROI ${stat.roi > 0 ? "+" : ""}${stat.roiDisplay} · ${label}`;
                    state.roiBadge.setAttribute("title", `${label} · ROI за всё время`);
                    setBadgeState(state.roiBadge, stat.roi);
                }
                visible.push({card, state, stat, sort: 0});
            }
        });

        if (code === "all") {
            visible.sort((a, b) => a.state.index - b.state.index);
        } else {
            visible.sort((a, b) => {
                const roiDiff = (b.stat?.roi || 0) - (a.stat?.roi || 0);
                if (roiDiff) return roiDiff;
                const predictionDiff = (b.stat?.predictions || 0) - (a.stat?.predictions || 0);
                if (predictionDiff) return predictionDiff;
                return a.state.index - b.state.index;
            });
            visible.forEach((item, index) => {
                if (item.state.rank) item.state.rank.textContent = `#${index + 1}`;
            });
        }

        visible.forEach((item) => grid.appendChild(item.card));
        cards.filter((card) => card.hidden).forEach((card) => grid.appendChild(card));

        count.textContent = `${visible.length} профилей`;
        buttons.forEach((button, buttonCode) => {
            const active = buttonCode === code;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", active ? "true" : "false");
        });
    };

    buttons.forEach((button, code) => {
        button.addEventListener("click", () => render(code));
    });

    render("all");
})();
