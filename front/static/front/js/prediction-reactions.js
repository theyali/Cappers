(() => {
    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const reactionKind = (button) => (
        button.classList.contains("prediction-favorite") ? "prediction-favorite" : "prediction-like"
    );

    const syncReactionCopies = (button, result) => {
        const card = button.closest("[data-prediction-card]");
        const predictionId = card?.dataset.predictionCard;
        if (!predictionId) return;

        const kind = reactionKind(button);
        document
            .querySelectorAll(`[data-prediction-card="${CSS.escape(predictionId)}"] .${kind}`)
            .forEach((copy) => {
                copy.classList.toggle("is-active", Boolean(result.active));
                copy.setAttribute("aria-pressed", result.active ? "true" : "false");
                copy.title = kind === "prediction-favorite"
                    ? (result.active ? "Убрать из избранного" : "Добавить в избранное")
                    : (result.active ? "Убрать лайк" : "Поставить лайк");

                const count = copy.querySelector("[data-like-count]");
                if (count && Number.isFinite(Number(result.count))) {
                    count.textContent = String(result.count);
                }
            });
    };

    const updateFavoritePage = (button, active) => {
        if (active || !button.classList.contains("prediction-favorite")) return;
        const page = document.querySelector("[data-favorites-page]");
        const card = button.closest("[data-prediction-card]");
        const predictionId = card?.dataset.predictionCard;
        if (!page || !predictionId) return;

        page
            .querySelectorAll(`[data-prediction-card="${CSS.escape(predictionId)}"]`)
            .forEach((copy) => copy.remove());

        const totalNode = page.querySelector(".predictions-total strong");
        if (totalNode) {
            const nextTotal = Math.max(0, Number.parseInt(totalNode.textContent || "0", 10) - 1);
            totalNode.textContent = String(nextTotal);
        }

        const remaining = page.querySelector("[data-prediction-card]");
        if (!remaining) window.location.reload();
    };

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-prediction-reaction]");
        if (!button || button.disabled) return;

        if (button.dataset.authenticated !== "true") {
            const loginUrl = button.dataset.loginUrl;
            if (loginUrl) window.location.assign(loginUrl);
            return;
        }

        const endpoint = button.dataset.url;
        if (!endpoint) return;

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

            if (response.redirected) {
                window.location.assign(response.url);
                return;
            }

            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Не удалось выполнить действие.");
            }

            syncReactionCopies(button, result);
            updateFavoritePage(button, Boolean(result.active));
        } catch (error) {
            console.error(error);
        } finally {
            if (button.isConnected) button.disabled = false;
        }
    });
})();
