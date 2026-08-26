(() => {
    const buttons = Array.from(document.querySelectorAll("[data-prediction-reaction]"));
    if (!buttons.length) return;

    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const csrftoken = decodeURIComponent(getCookie("csrftoken"));

    buttons.forEach((button) => {
        button.addEventListener("click", async () => {
            const endpoint = button.dataset.url;
            if (!endpoint) return;

            if (!csrftoken) {
                const loginUrl = button.dataset.loginUrl;
                if (loginUrl) window.location.assign(loginUrl);
                return;
            }

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

                if (response.redirected) {
                    window.location.assign(response.url);
                    return;
                }

                const result = await response.json();
                if (!response.ok || !result.ok) {
                    throw new Error(result.error || "Не удалось выполнить действие.");
                }

                button.classList.toggle("is-active", Boolean(result.active));
                button.setAttribute("aria-pressed", result.active ? "true" : "false");

                const count = button.querySelector("[data-like-count]");
                if (count && Number.isFinite(Number(result.count))) {
                    count.textContent = String(result.count);
                }

                if (button.classList.contains("prediction-favorite")) {
                    button.title = result.active ? "Убрать из избранного" : "Добавить в избранное";
                } else {
                    button.title = result.active ? "Убрать лайк" : "Поставить лайк";
                }
            } catch (error) {
                console.error(error);
            } finally {
                button.disabled = false;
            }
        });
    });
})();
