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
        const coverRadios = form.querySelectorAll("[data-rich-cover-radio]");
        const coverInputs = form.querySelectorAll(".rich-cover-option input[name='cover_image']");
        const coverMore = form.querySelector("[data-rich-cover-more]");
        const preview = document.querySelector("[data-rich-cover-preview]");
        if (!preview || (!customInput && !systemSelect && !coverRadios.length)) return;

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
            const checkedRadio = form.querySelector("[data-rich-cover-radio]:checked");
            setPreview(checkedRadio?.dataset.coverUrl || systemCovers.get(systemSelect?.value || "") || "");
        };

        systemSelect?.addEventListener("change", showSystemCover);
        coverInputs.forEach((input) => {
            input.closest(".rich-cover-option")?.addEventListener("click", (event) => {
                event.preventDefault();
                const scrollY = window.scrollY;
                input.checked = true;
                input.dispatchEvent(new Event("change", { bubbles: true }));
                requestAnimationFrame(() => window.scrollTo({ top: scrollY, left: window.scrollX }));
            });
        });
        coverRadios.forEach((radio) => {
            radio.addEventListener("change", showSystemCover);
        });
        coverMore?.addEventListener("click", () => {
            form.querySelectorAll(".rich-cover-option.is-extra[hidden]").forEach((node) => {
                node.hidden = false;
            });
            coverMore.hidden = true;
        });
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

    const initRichPredictionCouponEditor = () => {
        const form = document.querySelector(".rich-prediction-form");
        if (!form) return;

        const hiddenInput = form.querySelector("#id_remove_prediction_ids");
        const stakeInput = form.querySelector("#id_total_stake");
        const confidenceInput = form.querySelector("[data-rich-confidence]");
        const confidenceValue = form.querySelector("[data-rich-confidence-value]");
        const totalCoefficientNode = form.querySelector("[data-rich-total-coefficient]");
        const positionsCountNode = form.querySelector("[data-rich-positions-count]");
        const payoutNode = form.querySelector("[data-rich-payout]");

        const parseNumber = (value) => {
            const number = Number.parseFloat(String(value ?? "").replace(",", ".").replace(/\s+/g, ""));
            return Number.isFinite(number) ? number : 0;
        };

        const formatNumber = (value, digits = 0) => new Intl.NumberFormat("ru-RU", {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        }).format(value);

        const visibleCouponItems = () => Array.from(
            form.querySelectorAll("[data-rich-coupon-item]")
        ).filter((item) => !item.hidden);

        const recalcCouponSummary = () => {
            const visibleItems = visibleCouponItems();
            const totalCoefficient = visibleItems.reduce(
                (product, item) => product * Math.max(parseNumber(item.dataset.coefficient), 0),
                visibleItems.length ? 1 : 0
            );
            const stake = parseNumber(stakeInput?.value);
            if (totalCoefficientNode) totalCoefficientNode.textContent = formatNumber(totalCoefficient, 2);
            if (positionsCountNode) positionsCountNode.textContent = String(visibleItems.length);
            if (payoutNode) payoutNode.textContent = formatNumber(stake * totalCoefficient, 0);
        };

        if (confidenceInput && confidenceValue) {
            const syncConfidence = () => {
                confidenceValue.textContent = `${confidenceInput.value || 0}%`;
            };
            confidenceInput.addEventListener("input", syncConfidence);
            syncConfidence();
        }

        stakeInput?.addEventListener("input", recalcCouponSummary);
        recalcCouponSummary();

        if (!hiddenInput) return;

        const removed = new Set(
            String(hiddenInput.value || "")
                .split(",")
                .map((value) => value.trim())
                .filter(Boolean)
        );

        const syncRemoved = () => {
            hiddenInput.value = Array.from(removed).join(",");
        };

        form.addEventListener("click", (event) => {
            const button = event.target.closest("[data-rich-remove-prediction]");
            if (!button) return;

            event.preventDefault();
            const predictionId = button.dataset.richRemovePrediction;
            if (!predictionId) return;

            const item = button.closest("[data-rich-coupon-item]");
            const visibleItems = visibleCouponItems();
            if (visibleItems.length <= 1) {
                showFormError(form, "В купоне должна остаться минимум одна позиция.");
                return;
            }

            removed.add(predictionId);
            syncRemoved();

            if (item) item.hidden = true;
            showFormError(form, "");
            recalcCouponSummary();
        });
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
    initRichPredictionCouponEditor();
})();
