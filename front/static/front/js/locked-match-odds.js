(() => {
    const dataNode = document.getElementById("locked-match-odds-data");
    if (!dataNode) return;

    let cardData = {};
    try {
        cardData = JSON.parse(dataNode.textContent || "{}");
    } catch (error) {
        return;
    }

    const lockIcon = `
        <i class="match-odd-lock" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
                <path d="M7 10V8a5 5 0 0 1 10 0v2M6 10h12a2 2 0 0 1 2 2v7H4v-7a2 2 0 0 1 2-2Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </i>`;

    const items = [
        ["1", "home"],
        ["X", "draw"],
        ["2", "away"],
        ["ТБ 2.5", "over25"],
        ["ТМ 2.5", "under25"],
        ["ОЗ Да", "bttsYes"],
    ];

    Object.entries(cardData).forEach(([matchId, entry]) => {
        const card = document.querySelector(`[data-match-card][data-match-id="${matchId}"]`);
        if (!card || card.querySelector(".match-card-options")) return;

        const isLocked = entry?.scope === "live" || entry?.scope === "finished";
        const odds = entry?.odds || {};
        const options = document.createElement("div");
        options.className = `coupon-options match-card-options ${isLocked ? "is-locked" : "is-readonly"}`;
        options.setAttribute(
            "aria-label",
            isLocked ? "Коэффициенты закрыты" : "Коэффициенты матча",
        );

        items.forEach(([label, key]) => {
            const odd = odds[key] || "";
            const button = document.createElement("button");
            button.className = "coupon-option match-bet-option";
            button.type = "button";
            button.disabled = true;
            button.setAttribute("aria-disabled", "true");
            button.title = isLocked
                ? "Матч уже идет или завершен. Коэффициент доступен только для просмотра."
                : "Коэффициент доступен для просмотра. Добавлять исходы в прогноз могут эксперты.";
            button.innerHTML = `${isLocked || !odd ? lockIcon : ""}<span></span>${odd ? "<small></small>" : ""}`;
            button.querySelector("span").textContent = label;
            if (odd) button.querySelector("small").textContent = odd;
            options.append(button);
        });

        card.append(options);
    });
})();
