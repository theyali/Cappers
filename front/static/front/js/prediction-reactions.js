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

                const count = copy.querySelector("[data-reaction-count], [data-like-count]");
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

    const copyShareUrl = async (shareUrl) => {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(shareUrl);
            return;
        }

        const textarea = document.createElement("textarea");
        textarea.value = shareUrl;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) throw new Error("Не удалось скопировать ссылку.");
    };

    const incrementShareCount = async (button) => {
        const endpoint = button.dataset.shareEndpoint;
        if (!endpoint) return;

        const csrftoken = decodeURIComponent(getCookie("csrftoken"));
        if (!csrftoken) return;

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
            throw new Error(result.error || "Не удалось обновить счетчик репостов.");
        }

        const predictionId = button.dataset.predictionId;
        if (!predictionId) return;
        document
            .querySelectorAll(`.prediction-share[data-prediction-id="${CSS.escape(predictionId)}"] [data-share-count]`)
            .forEach((count) => {
                count.textContent = String(result.shares_count);
            });
    };

    const sharePrediction = async (button) => {
        const rawShareUrl = button.dataset.shareUrl;
        if (!rawShareUrl) return;

        const shareUrl = new URL(rawShareUrl, window.location.origin).href;
        if (navigator.share) {
            await navigator.share({ url: shareUrl });
        } else {
            await copyShareUrl(shareUrl);
        }
        await incrementShareCount(button);
    };

    const showFormError = (form, message) => {
        const status = form.querySelector("[data-form-client-error]");
        if (!status) return;

        status.hidden = !message;
        status.textContent = message || "";
        if (message) status.focus?.();
    };

    const lockFormSubmit = (form, submitter) => {
        if (submitter?.name && submitter.value) {
            const hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = submitter.name;
            hidden.value = submitter.value;
            form.appendChild(hidden);
        }

        form.setAttribute("aria-busy", "true");
        form
            .querySelectorAll('button[type="submit"], input[type="submit"]')
            .forEach((button) => {
                button.disabled = true;
                button.setAttribute("aria-disabled", "true");
            });
    };

    const initSubmitLocks = () => {
        document.querySelectorAll("form[data-disable-on-submit]").forEach((form) => {
            form.addEventListener("submit", (event) => {
                showFormError(form, "");
                lockFormSubmit(form, event.submitter);
            });
        });
    };

    const initRichCoverPreview = () => {
        const form = document.querySelector(".rich-prediction-form");
        if (!form) return;

        const customInput = form.querySelector("#id_custom_cover_image");
        const systemSelect = form.querySelector("#id_cover_image");
        const preview = document.querySelector("[data-rich-cover-preview]");
        if (!preview || (!customInput && !systemSelect)) return;

        const systemCovers = new Map(
            Array.from(document.querySelectorAll("[data-rich-cover-option]"))
                .map((node) => [node.dataset.coverId, node.dataset.coverUrl])
                .filter(([, url]) => Boolean(url))
        );
        let objectUrl = "";

        const setPreview = (url) => {
            let image = preview.querySelector("[data-rich-cover-preview-image]");
            const empty = preview.querySelector("[data-rich-cover-preview-empty]");

            if (!url) {
                image?.remove();
                if (empty) empty.hidden = false;
                return;
            }

            if (!image) {
                image = document.createElement("img");
                image.width = 640;
                image.height = 400;
                image.alt = "";
                image.dataset.richCoverPreviewImage = "";
                preview.prepend(image);
            }

            image.src = url;
            if (empty) empty.hidden = true;
        };

        const showSystemCover = () => {
            if (customInput?.files?.length) return;
            setPreview(systemCovers.get(systemSelect?.value || "") || "");
        };

        systemSelect?.addEventListener("change", showSystemCover);
        customInput?.addEventListener("change", () => {
            showFormError(form, "");

            const file = customInput.files?.[0];
            if (!file) {
                if (objectUrl) URL.revokeObjectURL(objectUrl);
                objectUrl = "";
                showSystemCover();
                return;
            }

            const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
            if (!allowedTypes.has(file.type)) {
                customInput.value = "";
                showFormError(form, "Разрешены только JPG, PNG и WebP.");
                showSystemCover();
                return;
            }

            if (file.size > 5 * 1024 * 1024) {
                customInput.value = "";
                showFormError(form, "Обложка не должна быть больше 5 МБ.");
                showSystemCover();
                return;
            }

            if (objectUrl) URL.revokeObjectURL(objectUrl);
            objectUrl = URL.createObjectURL(file);
            setPreview(objectUrl);
        });

        window.addEventListener("pagehide", () => {
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        }, { once: true });
    };

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-prediction-reaction]");
        if (!button) return;

        if (button.closest(".is-own-prediction")) {
            button.disabled = true;
            button.setAttribute("aria-disabled", "true");
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

    document.addEventListener("click", async (event) => {
        const button = event.target.closest(".prediction-share");
        if (!button || button.disabled) return;

        button.disabled = true;
        try {
            await sharePrediction(button);
        } catch (error) {
            if (error?.name !== "AbortError") {
                console.error(error);
                button.title = error?.message || "Не удалось поделиться прогнозом.";
                button.setAttribute("aria-label", button.title);
            }
        } finally {
            if (button.isConnected) button.disabled = false;
        }
    });

    initSubmitLocks();
    initRichCoverPreview();
})();
