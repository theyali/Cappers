(() => {
    const dataNode = document.getElementById("locked-match-odds-data");
    if (!dataNode) return;

    let oddsByMatch = {};
    try {
        oddsByMatch = JSON.parse(dataNode.textContent || "{}");
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

    Object.entries(oddsByMatch).forEach(([matchId, odds]) => {
        const card = document.querySelector(`[data-match-card][data-match-id="${CSS.escape(matchId)}"]`);
        if (!card || card.querySelector(".match-card-options")) return;

        const options = document.createElement("div");
        options.className = "coupon-options match-card-options is-locked";
        options.setAttribute("aria-label", "Коэффициенты закрыты");

        items.forEach(([label, key]) => {
            const button = document.createElement("button");
            button.className = "coupon-option match-bet-option";
            button.type = "button";
            button.disabled = true;
            button.setAttribute("aria-disabled", "true");
            button.title = "Матч уже идет или завершен. Коэффициент доступен только для просмотра.";
            button.innerHTML = `${lockIcon}<span></span><small></small>`;
            button.querySelector("span").textContent = label;
            button.querySelector("small").textContent = odds?.[key] || "—";
            options.append(button);
        });

        card.append(options);
    });
})();
