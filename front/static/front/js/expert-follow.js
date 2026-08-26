(() => {
    const buttons = Array.from(document.querySelectorAll("[data-expert-follow]"));
    if (!buttons.length) return;

    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const syncButtons = (url, active) => {
        buttons
            .filter((item) => item.dataset.url === url)
            .forEach((item) => {
                item.classList.toggle("is-active", Boolean(active));
                item.setAttribute("aria-pressed", active ? "true" : "false");
                const label = item.querySelector("[data-follow-label]");
                if (label) label.textContent = active ? "Вы подписаны" : "Подписаться";
            });
    };

    buttons.forEach((button) => {
        button.addEventListener("click", async () => {
            if (button.disabled || !button.dataset.url) return;
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

                const followers = button
                    .closest("[data-follow-card]")
                    ?.querySelector("[data-followers-count]")
                    || document.querySelector("[data-followers-count]");
                if (followers) followers.textContent = String(result.followers_count);
            } catch (error) {
                console.error(error);
            } finally {
                button.disabled = false;
            }
        });
    });
})();
