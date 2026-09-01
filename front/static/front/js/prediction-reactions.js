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

    const ownReactionTitle = (button) => (
        reactionKind(button) === "prediction-favorite"
            ? "Нельзя сохранять свой прогноз в избранное"
            : "Нельзя лайкать свой прогноз"
    );

    const lockOwnPredictionReactions = (root = document) => {
        const ownPredictions = [];
        if (root instanceof Element && root.matches(".is-own-prediction")) {
            ownPredictions.push(root);
        }
        if (root.querySelectorAll) {
            ownPredictions.push(...root.querySelectorAll(".is-own-prediction"));
        }

        ownPredictions.forEach((prediction) => {
            prediction.querySelectorAll("[data-prediction-reaction]").forEach((button) => {
                button.disabled = true;
                button.setAttribute("aria-disabled", "true");
                button.style.cursor = "not-allowed";
                button.title = ownReactionTitle(button);
            });
        });
    };

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

    lockOwnPredictionReactions();

    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node instanceof Element) lockOwnPredictionReactions(node);
            });
        });
    });
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    }

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-prediction-reaction]");
        if (!button) return;

        if (button.closest(".is-own-prediction")) {
            button.disabled = true;
            button.setAttribute("aria-disabled", "true");
            button.style.cursor = "not-allowed";
            button.title = ownReactionTitle(button);
            return;
        }
        if (button.disabled) return;

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
            if (button.isConnected && !button.closest(".is-own-prediction")) {
                button.disabled = false;
            }
        }
    });
})();
