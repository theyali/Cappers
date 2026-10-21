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

    const updateFavoritesFilter = (button, active) => {
        if (active || !button.classList.contains("prediction-favorite")) return;
        const isFavoritesFeed = window.location.pathname === "/feed/"
            && new URLSearchParams(window.location.search).get("favorites") === "1";
        if (!isFavoritesFeed) return;

        const card = button.closest("[data-prediction-card]");
        const predictionId = card?.dataset.predictionCard;
        if (!predictionId) return;

        document
            .querySelectorAll(`[data-prediction-card="${CSS.escape(predictionId)}"]`)
            .forEach((copy) => copy.remove());

        const totalNode = document.querySelector(".predictions-total strong, .paid-feed-head > strong");
        if (totalNode) {
            const nextTotal = Math.max(0, Number.parseInt(totalNode.textContent || "0", 10) - 1);
            totalNode.textContent = String(nextTotal);
        }

        const remaining = document.querySelector("[data-prediction-card]");
        if (!remaining) document.querySelector("[data-predictions-lazy]")?.remove();
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
                const blockedMatch = form.querySelector("[data-rich-coupon-item].is-timing-locked:not([hidden])");
                if (blockedMatch) {
                    event.preventDefault();
                    showFormError(form, "Удалите отмеченные красным недоступные матчи перед публикацией.");
                    blockedMatch.focus();
                    return;
                }
                if (form.dataset.removingPrediction === "true") {
                    event.preventDefault();
                    showFormError(form, "Дождитесь удаления матча из купона.");
                    return;
                }
                showFormError(form, "");
                lockFormSubmit(form, event.submitter);
            });
        });
    };

    const initRichSharedDraft = () => {
        const page = document.querySelector("[data-shared-coupon-page]");
        const form = page?.querySelector("[data-shared-coupon-editor]");
        if (!page || !window.CappersCouponDraft) return;
        let revision = window.CappersCouponDraft.get()?.revision || form?.dataset.draftRevision;
        window.addEventListener("coupon:draft-changed", (event) => {
            const payload = event.detail;
            if (!form) {
                if (payload.draft?.items?.length) window.location.reload();
                return;
            }
            const paid = form.querySelector("[data-rich-paid-option]");
            const settingsNote = form.querySelector("[data-rich-paid-settings-note]");
            if (typeof payload.paid_available === "boolean") {
                if (paid) {
                    paid.disabled = !payload.paid_available;
                    paid.closest("label")?.classList.toggle("is-locked", !payload.paid_available);
                    if (!payload.paid_available && paid.checked) {
                        const free = form.querySelector('[name="is_paid"][value=""]');
                        if (free) free.checked = true;
                    }
                }
                if (settingsNote) settingsNote.hidden = payload.paid_available;
                form.dispatchEvent(new Event("change", { bubbles: true }));
            }
            const draft = payload.draft;
            if (!draft || String(draft.id) !== form.dataset.couponId) {
                window.location.reload();
                return;
            }
            if (draft.revision === revision) return;
            if (typeof payload.editor_html !== "string") { window.CappersCouponDraft.refresh(); return; }
            revision = draft.revision;
            const revisionInput = form.querySelector("#id_draft_revision");
            if (revisionInput) revisionInput.value = revision;
            const list = form.querySelector(".rich-prediction-coupon-list");
            if (list) list.innerHTML = payload.editor_html;
            const removed = form.querySelector("#id_remove_prediction_ids");
            if (removed) removed.value = "";
            form.dispatchEvent(new Event("rich:coupon-replaced"));
        });
    };

    const initRichPredictionPreview = () => {
        const form = document.querySelector(".rich-prediction-form");
        if (!form) return;
        const headline = form.querySelector("#id_headline");
        const description = form.querySelector("#id_description");
        const stake = form.querySelector("#id_total_stake");
        const confidence = form.querySelector("[data-rich-confidence]");
        const minimum = Number(form.dataset.paidDescriptionMinLength) || 300;
        const previewHeadline = document.querySelector("[data-rich-preview-headline]");
        const paidBadge = document.querySelector("[data-rich-preview-paid]");
        const isPaid = () => Boolean(form.querySelector('[name="is_paid"]:checked')?.value);
        const descriptionLength = () => Array.from(description?.value.trim() || "").length;
        const sync = () => {
            const paid = isPaid();
            if (previewHeadline) previewHeadline.textContent = headline?.value.trim() || "Заголовок вашего прогноза";
            if (paidBadge) paidBadge.hidden = !paid;
            [headline, description].forEach((field) => {
                if (!field) return;
                field.required = paid;
                field.setAttribute("aria-required", String(paid));
            });
            if (description) description.minLength = paid ? minimum : 0;
            const checks = {
                matches: Array.from(form.querySelectorAll("[data-rich-coupon-item]")).some((item) => !item.hidden),
                stake: Number(stake?.value) >= 100 && Number(stake?.value) <= 1000000
                    && confidence?.value !== "" && Number(confidence?.value) >= 0 && Number(confidence?.value) <= 100,
                headline: Boolean(headline?.value.trim()),
                description: descriptionLength() >= minimum,
                cover: Boolean(form.querySelector('[data-rich-cover-radio]:checked') || form.querySelector('#id_custom_cover_image')?.files?.length
                    || document.querySelector('[data-rich-cover-preview-image]')),
            };
            document.querySelectorAll("[data-rich-check]").forEach((item) => {
                const done = Boolean(checks[item.dataset.richCheck]);
                item.classList.toggle("is-done", done);
                item.setAttribute("aria-label", `${item.textContent.trim()}: ${done ? "готово" : "не заполнено"}`);
            });
            if (!paid || headline?.value.trim()) headline?.removeAttribute("aria-invalid");
            if (!paid || descriptionLength() >= minimum) description?.removeAttribute("aria-invalid");
        };
        form.addEventListener("input", sync);
        form.addEventListener("change", sync);
        form.addEventListener("rich:coupon-updated", sync);
        // Capture runs before the shared submit lock, including external publish buttons.
        form.addEventListener("submit", (event) => {
            if (!isPaid()) return;
            const missingHeadline = !headline?.value.trim();
            const shortDescription = descriptionLength() < minimum;
            if (!missingHeadline && !shortDescription) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            const field = missingHeadline ? headline : description;
            field?.setAttribute("aria-invalid", "true");
            showFormError(form, missingHeadline
                ? "Для платного прогноза обязательно укажите заголовок."
                : `Для платного прогноза добавьте описание от ${minimum} символов.`);
            field?.setAttribute("aria-describedby", "rich-prediction-client-error");
            field?.focus();
        }, true);
        sync();
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
        const confidenceValues = document.querySelectorAll("[data-rich-confidence-value]");
        const totalCoefficientNodes = document.querySelectorAll("[data-rich-total-coefficient]");
        const positionsCountNodes = document.querySelectorAll("[data-rich-positions-count]");
        const stakeSummaryNodes = document.querySelectorAll("[data-rich-stake-summary]");
        const payoutNodes = document.querySelectorAll("[data-rich-payout]");
        const moreMatchesButton = form.querySelector(".rich-prediction-more-matches");

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

        let matchesExpanded = false;
        const recalcCouponSummary = () => {
            const visibleItems = visibleCouponItems();
            visibleItems.forEach((item, index) => {
                const number = item.querySelector(".rich-prediction-item-number");
                if (number) number.textContent = String(index + 1);
                item.classList.toggle("is-mobile-extra", !matchesExpanded && index >= 3);
            });
            if (moreMatchesButton) {
                moreMatchesButton.hidden = matchesExpanded || visibleItems.length <= 3;
                moreMatchesButton.textContent = `Показать ещё (${Math.max(0, visibleItems.length - 3)})`;
            }
            const totalCoefficient = visibleItems.reduce(
                (product, item) => product * Math.max(parseNumber(item.dataset.coefficient), 0),
                visibleItems.length ? 1 : 0
            );
            const stake = parseNumber(stakeInput?.value);
            totalCoefficientNodes.forEach((node) => {
                node.textContent = formatNumber(totalCoefficient, 2);
            });
            positionsCountNodes.forEach((node) => {
                node.textContent = String(visibleItems.length);
            });
            stakeSummaryNodes.forEach((node) => {
                node.textContent = formatNumber(stake, 0);
            });
            payoutNodes.forEach((node) => {
                node.textContent = formatNumber(stake * totalCoefficient, 0);
            });
            form.dispatchEvent(new Event("rich:coupon-updated"));
        };

        if (confidenceInput && confidenceValues.length) {
            const syncConfidence = () => {
                confidenceValues.forEach((node) => { node.textContent = `${confidenceInput.value || 0}%`; });
            };
            confidenceInput.addEventListener("input", syncConfidence);
            syncConfidence();
        }

        form.addEventListener("rich:coupon-replaced", recalcCouponSummary);
        stakeInput?.addEventListener("input", recalcCouponSummary);
        recalcCouponSummary();

        moreMatchesButton?.addEventListener("click", () => {
            matchesExpanded = true;
            recalcCouponSummary();
        });

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

        form.addEventListener("click", async (event) => {
            const button = event.target.closest("[data-rich-remove-prediction]");
            if (!button) return;

            event.preventDefault();
            const predictionId = button.dataset.richRemovePrediction;
            if (!predictionId || form.dataset.removingPrediction === "true") return;

            const item = button.closest("[data-rich-coupon-item]");

            form.dataset.removingPrediction = "true";
            const buttons = Array.from(document.querySelectorAll(
                '.rich-prediction-form button[type="submit"], button[form="rich-prediction-form"], [data-rich-remove-prediction]'
            )).filter((control) => !control.disabled);
            buttons.forEach((control) => { control.disabled = true; });
            button.setAttribute("aria-busy", "true");
            showFormError(form, "");
            try {
                const response = await fetch(button.dataset.removeUrl, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": form.querySelector('[name="csrfmiddlewaretoken"]')?.value || decodeURIComponent(getCookie("csrftoken")),
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json",
                    },
                    credentials: "same-origin",
                });
                const payload = await response.json();
                if (!response.ok || !payload.ok) throw new Error(payload.error || "Не удалось удалить матч.");
                if (payload.cleared) {
                    // The last match took the draft with it: show the empty editor.
                    window.location.reload();
                    return;
                }
                removed.add(predictionId);
                syncRemoved();
                item?.remove();
                recalcCouponSummary();
                if (form.hasAttribute("data-shared-coupon-editor")) window.CappersCouponDraft?.changed();
            } catch (error) {
                showFormError(form, error instanceof SyntaxError
                    ? "Не удалось удалить матч. Обновите страницу и повторите попытку."
                    : error.message || "Не удалось удалить матч. Попробуйте ещё раз.");
            } finally {
                form.dataset.removingPrediction = "false";
                button.removeAttribute("aria-busy");
                buttons.forEach((control) => { control.disabled = false; });
                form.dispatchEvent(new Event("rich:coupon-updated"));
            }
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
            updateFavoritesFilter(button, Boolean(result.active));
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
    initRichPredictionPreview();
    initRichSharedDraft();
})();
