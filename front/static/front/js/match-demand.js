(() => {
    const section = document.querySelector("[data-match-demand]");
    if (!section || section.dataset.matchDemandReady === "true") return;
    section.dataset.matchDemandReady = "true";

    const button = section.querySelector("[data-match-demand-toggle]");
    if (!button) return;

    const toggleUrl = section.dataset.toggleUrl;
    if (!toggleUrl) return;

    const count = section.querySelector("[data-match-demand-count]");
    const text = section.querySelector("[data-match-demand-button-text]");
    const status = section.querySelector("[data-match-demand-status]");

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
                cache: "no-store",
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
})();
