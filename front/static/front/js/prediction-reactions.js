(() => {
    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const updateFavoritePage = (button, active) => {
        if (active || !button.classList.contains("prediction-favorite")) return;
        const page = document.querySelector("[data-favorites-page]");
        const card = button.closest("[data-prediction-card]");
        if (!page || !card) return;

        card.remove();
        const totalNode = page.querySelector(".predictions-total strong");
        if (totalNode) {
            const nextTotal = Math.max(0, Number.parseInt(totalNode.textContent || "0", 10) - 1);
            totalNode.textContent = String(nextTotal);
        }

        const grid = page.querySelector("[data-favorites-grid]");
        if (grid && !grid.querySelector("[data-prediction-card]")) {
            window.location.reload();
        }
    };

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-prediction-reaction]");
        if (!button || button.disabled) return;

        const endpoint = button.dataset.url;
        if (!endpoint) return;

        const csrftoken = decodeURIComponent(getCookie("csrftoken"));
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

            updateFavoritePage(button, Boolean(result.active));
        } catch (error) {
            console.error(error);
        } finally {
            if (button.isConnected) button.disabled = false;
        }
    });
})();
