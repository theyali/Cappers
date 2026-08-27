(() => {
    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const syncAnalystState = (analystId, active) => {
        document.querySelectorAll(`[data-prediction-follow][data-analyst-id="${analystId}"]`).forEach((button) => {
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", active ? "true" : "false");
            button.setAttribute("aria-label", active ? "Отписаться от эксперта" : "Подписаться на эксперта");
            button.setAttribute("title", active ? "Отписаться" : "Подписаться");

            const subscribeIcon = button.querySelector('[data-follow-icon="subscribe"]');
            const unsubscribeIcon = button.querySelector('[data-follow-icon="unsubscribe"]');
            if (subscribeIcon) subscribeIcon.hidden = active;
            if (unsubscribeIcon) unsubscribeIcon.hidden = !active;

            const label = button.querySelector("[data-follow-label]");
            if (label) label.textContent = active ? "Отписаться" : "Подписаться";
        });

        document.querySelectorAll(`[data-prediction-card][data-analyst-id="${analystId}"]`).forEach((card) => {
            if (card.classList.contains("is-own-prediction")) return;
            card.classList.toggle("is-followed-prediction", active);
        });
    };

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-prediction-follow]");
        if (!button || button.disabled) return;

        const endpoint = button.dataset.url;
        const analystId = button.dataset.analystId;
        if (!endpoint || !analystId) return;

        const csrftoken = decodeURIComponent(getCookie("csrftoken"));
        if (!csrftoken) return;

        button.disabled = true;
        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrftoken,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Не удалось изменить подписку.");
            }
            syncAnalystState(analystId, Boolean(result.active));
        } catch (error) {
            console.error(error);
        } finally {
            button.disabled = false;
        }
    });
})();
