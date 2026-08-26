(() => {
    const button = document.querySelector("[data-expert-follow]");
    if (!button) return;

    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

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

            button.classList.toggle("is-active", Boolean(result.active));
            button.setAttribute("aria-pressed", result.active ? "true" : "false");
            const label = button.querySelector("[data-follow-label]");
            if (label) label.textContent = result.active ? "Вы подписаны" : "Подписаться";

            const followers = document.querySelector("[data-followers-count]");
            if (followers) followers.textContent = String(result.followers_count);
        } catch (error) {
            console.error(error);
        } finally {
            button.disabled = false;
        }
    });
})();
