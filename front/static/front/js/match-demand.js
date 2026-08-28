(() => {
    const bets = document.querySelector("[data-match-bets][data-match-id]");
    const matchCard = document.querySelector(".match-detail-card");
    if (!bets || !matchCard || document.querySelector("[data-match-demand]")) return;

    const matchId = Number(bets.dataset.matchId || 0);
    if (!matchId) return;

    const loadStyles = () => {
        if (document.querySelector("link[data-match-demand-styles]")) return;
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "/static/front/css/match-demand.css";
        link.dataset.matchDemandStyles = "true";
        document.head.appendChild(link);
    };

    const getCookie = (name) => {
        const cookies = document.cookie ? document.cookie.split(";") : [];
        for (const cookie of cookies) {
            const trimmed = cookie.trim();
            if (trimmed.startsWith(`${name}=`)) {
                return decodeURIComponent(trimmed.slice(name.length + 1));
            }
        }
        return "";
    };

    const stateUrl = `/games/demand/${matchId}/`;
    const toggleUrl = `/games/demand/${matchId}/toggle/`;

    fetch(stateUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
    })
        .then(async (response) => {
            const payload = await response.json();
            if (!response.ok || !payload?.ok) {
                throw new Error(payload?.error || "Не удалось загрузить спрос на прогноз.");
            }
            return payload;
        })
        .then((payload) => {
            if (!payload.available) return;
            loadStyles();

            const section = document.createElement("section");
            section.className = "match-demand-card";
            section.dataset.matchDemand = "";
            section.setAttribute("aria-label", "Хочу прогноз на матч");

            const buttonHtml = payload.authenticated
                ? `<button class="match-demand-button${payload.active ? " is-active" : ""}" type="button" data-match-demand-toggle aria-pressed="${payload.active ? "true" : "false"}">
                    <span data-match-demand-button-text>${payload.active ? "Запрос отправлен" : "Хочу прогноз"}</span>
                  </button>`
                : `<a class="match-demand-login" href="/cabinet/login/?next=${encodeURIComponent(window.location.pathname + window.location.search)}">Хочу прогноз</a>`;

            section.innerHTML = `
                <div class="match-demand-main">
                    <span class="match-demand-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24"><path d="M4 5h16v11H9l-5 4V5Z"></path><path d="M8 9h8M8 12h5"></path></svg>
                    </span>
                    <div class="match-demand-copy">
                        <span class="match-demand-kicker">Спрос на прогноз</span>
                        <strong>Хотите прогноз на этот матч?</strong>
                        <p>Отметьте матч — капперы увидят спрос в личном кабинете.</p>
                        <div class="match-demand-status" data-match-demand-status aria-live="polite"></div>
                    </div>
                </div>
                <div class="match-demand-actions">
                    <div class="match-demand-count">
                        <strong data-match-demand-count>${Number(payload.requests_count) || 0}</strong>
                        <span>запросов на прогноз</span>
                    </div>
                    ${buttonHtml}
                </div>`;

            matchCard.insertAdjacentElement("afterend", section);

            const button = section.querySelector("[data-match-demand-toggle]");
            if (!button) return;

            const count = section.querySelector("[data-match-demand-count]");
            const text = section.querySelector("[data-match-demand-button-text]");
            const status = section.querySelector("[data-match-demand-status]");

            const setState = (active, requestsCount) => {
                button.classList.toggle("is-active", Boolean(active));
                button.setAttribute("aria-pressed", active ? "true" : "false");
                if (text) text.textContent = active ? "Запрос отправлен" : "Хочу прогноз";
                if (count) count.textContent = String(Number(requestsCount) || 0);
            };

            button.addEventListener("click", async () => {
                if (button.disabled) return;
                button.disabled = true;
                status?.classList.remove("is-error");
                if (status) status.textContent = "Сохраняем…";

                try {
                    const response = await fetch(toggleUrl, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            "X-CSRFToken": getCookie("csrftoken"),
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    });
                    const result = await response.json();
                    if (!response.ok || !result?.ok) {
                        throw new Error(result?.error || "Не удалось обновить запрос.");
                    }
                    setState(result.active, result.requests_count);
                    if (status) status.textContent = result.message || "Готово";
                    window.setTimeout(() => {
                        if (status) status.textContent = "";
                    }, 1800);
                } catch (error) {
                    if (status) {
                        status.textContent = error?.message || "Не удалось обновить запрос.";
                        status.classList.add("is-error");
                    }
                } finally {
                    button.disabled = false;
                }
            });
        })
        .catch((error) => console.error(error));
})();
