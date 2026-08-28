(() => {
    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const syncButtons = (url, active) => {
        document.querySelectorAll("[data-expert-follow]").forEach((item) => {
            if (item.dataset.url !== url) return;
            item.classList.toggle("is-active", Boolean(active));
            item.setAttribute("aria-pressed", active ? "true" : "false");
            const label = item.querySelector("[data-follow-label]");
            if (label) label.textContent = active ? "Вы подписаны" : "Подписаться";
        });
    };

    const updateCounter = (node, value) => {
        if (!node) return;
        node.textContent = String(value);
        node.animate?.(
            [
                { transform: "scale(1)" },
                { transform: "scale(1.12)" },
                { transform: "scale(1)" },
            ],
            { duration: 220, easing: "ease-out" },
        );
    };

    const syncFollowersCount = (button, followersCount) => {
        const value = Number(followersCount);
        if (!Number.isFinite(value)) return;

        const card = button.closest("[data-follow-card]");
        if (card) {
            card.querySelectorAll("[data-followers-count]").forEach((node) => {
                updateCounter(node, value);
            });
        }

        document
            .querySelectorAll(".expert-public-page [data-followers-count]")
            .forEach((node) => updateCounter(node, value));
    };

    document.addEventListener("click", async (event) => {
        if (!(event.target instanceof Element)) return;

        const button = event.target.closest("[data-expert-follow]");
        if (!button || button.disabled || !button.dataset.url) return;

        event.preventDefault();
        button.disabled = true;

        try {
            const response = await fetch(button.dataset.url, {
                method: "POST",
                headers: {
                    "X-CSRFToken": decodeURIComponent(getCookie("csrftoken")),
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Не удалось изменить подписку.");
            }

            syncButtons(button.dataset.url, Boolean(result.active));
            syncFollowersCount(button, result.followers_count);
        } catch (error) {
            console.error(error);
        } finally {
            button.disabled = false;
        }
    });
})();
