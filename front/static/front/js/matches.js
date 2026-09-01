(() => {
    const root = document.querySelector("[data-coupon-page]");
    if (!root) return;

    const sidebar = root.querySelector(".coupon-sidebar");
    const sidebarToggle = root.querySelector("[data-sidebar-toggle]");
    if (sidebar && sidebarToggle) {
        sidebarToggle.addEventListener("click", () => {
            const isCollapsed = sidebar.classList.toggle("is-collapsed");
            sidebarToggle.setAttribute("aria-expanded", String(!isCollapsed));
        });
    }

    const scrollAnimations = new WeakMap();

    const stopNameScroll = (node) => {
        const animation = scrollAnimations.get(node);
        if (animation) {
            cancelAnimationFrame(animation.frame);
            window.clearTimeout(animation.timeout);
        }
        scrollAnimations.delete(node);
        node.scrollLeft = 0;
    };

    const startNameScroll = (node) => {
        stopNameScroll(node);
        const distance = node.scrollWidth - node.clientWidth;
        if (distance <= 2) return;

        const duration = Math.max(1600, Math.min(5200, distance * 42));
        const timeout = window.setTimeout(() => {
            let startedAt = null;
            const step = (timestamp) => {
                if (!startedAt) startedAt = timestamp;
                const progress = Math.min((timestamp - startedAt) / duration, 1);
                node.scrollLeft = distance * progress;
                if (progress < 1) {
                    const frame = requestAnimationFrame(step);
                    scrollAnimations.set(node, { frame, timeout });
                }
            };
            const frame = requestAnimationFrame(step);
            scrollAnimations.set(node, { frame, timeout });
        }, 250);
        scrollAnimations.set(node, { frame: 0, timeout });
    };

    const initScrollableNames = (scope = document) => {
        scope.querySelectorAll(".match-league strong, .match-league small, .match-team strong, .match-detail-team strong, .odds-button span, .odds-button small, .coupon-item-title strong, .coupon-item-title span, .coupon-pick strong").forEach((node) => {
            if (node.dataset.scrollNameReady === "true") return;
            node.dataset.scrollNameReady = "true";
            node.addEventListener("mouseenter", () => startNameScroll(node));
            node.addEventListener("mouseleave", () => stopNameScroll(node));
            node.addEventListener("focus", () => startNameScroll(node));
            node.addEventListener("blur", () => stopNameScroll(node));
        });
    };

    initScrollableNames(root);
    document.addEventListener("matches:appended", (event) => {
        (event.detail?.nodes || []).forEach((node) => initScrollableNames(node));
    });

    root.querySelectorAll("[data-odds-tab-target]").forEach((button) => {
        button.addEventListener("click", () => {
            const target = button.dataset.oddsTabTarget;
            root.querySelectorAll("[data-odds-tab-target]").forEach((tabButton) => {
                const isActive = tabButton === button;
                tabButton.classList.toggle("is-active", isActive);
                tabButton.setAttribute("aria-selected", String(isActive));
            });
            root.querySelectorAll("[data-odds-tab-panel]").forEach((panel) => {
                panel.classList.toggle("is-active", panel.dataset.oddsTabPanel === target);
            });
        });
    });

    const form = root.querySelector("[data-coupon-form]");
    if (!form) return;

    const itemsRoot = root.querySelector("[data-coupon-items]");
    const countNode = root.querySelector("[data-coupon-count]");
    const stakeInput = root.querySelector("[data-coupon-stake]");
    const confidenceInput = root.querySelector("[data-coupon-confidence]");
    const confidenceValue = root.querySelector("[data-coupon-confidence-value]");
    const confidenceFill = root.querySelector("[data-coupon-confidence-fill]");
    const coefficientNode = root.querySelector("[data-coupon-coefficient]");
    const totalNode = root.querySelector("[data-coupon-total]");
    const noteNode = root.querySelector("[data-coupon-note]");
    const submitButton = root.querySelector("[data-coupon-submit]");
    const submitStatus = root.querySelector("[data-coupon-submit-status]");
    const csrfInput = form.querySelector("[name=csrfmiddlewaretoken]");
    const canWrite = root.dataset.canWrite === "true";
    const createUrl = root.dataset.createUrl;
    const staleSeconds = Number.parseInt(root.dataset.staleSeconds || "60", 10) || 60;
    const autosaveEnabled = root.dataset.autosave !== "false";
    const minConfidence = Math.max(0, Math.min(100, Number.parseInt(root.dataset.minConfidence || "0", 10) || 0));
    const couponTypeRule = root.dataset.couponTypeRule || "any";
    const csrfCookie = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] || "session";
    const userKey = root.dataset.userId || csrfCookie;
    const storageKey = `cappers:coupon-draft:${userKey}`;
    const items = new Map();

    let draftId = null;
    let autosaveTimer = null;
    let autosaveRequest = null;
    let manualRequest = null;
    let restoring = true;

    const toNumber = (value, fallback = 0) => {
        const parsed = Number.parseFloat(String(value ?? "").replace(",", "."));
        return Number.isFinite(parsed) ? parsed : fallback;
    };

    const normalizeConfidence = (value) => {
        const parsed = Number.parseInt(String(value ?? "50"), 10);
        if (!Number.isFinite(parsed)) return Math.max(50, minConfidence);
        return Math.max(minConfidence, Math.min(100, parsed));
    };

    const currentConfidence = () => normalizeConfidence(confidenceInput?.value);
    const hasPositiveStake = () => toNumber(stakeInput?.value) > 0;

    const couponCountMatchesRule = () => {
        if (items.size < 1 || items.size > 20) return false;
        if (couponTypeRule === "single") return items.size === 1;
        if (couponTypeRule === "express") return items.size >= 2;
        return true;
    };

    const couponIsComplete = () => (
        couponCountMatchesRule()
        && hasPositiveStake()
        && currentConfidence() >= minConfidence
        && currentConfidence() <= 100
        && [...items.values()].every((item) => (
            String(item.selection || "").trim().length > 0
            && toNumber(item.coefficient) > 0
        ))
    );

    const setNote = (message, state = "") => {
        if (!noteNode) return;
        noteNode.textContent = message;
        noteNode.classList.toggle("is-error", state === "error");
        noteNode.classList.toggle("is-success", state === "success");
    };

    const formatMoney = (value) => value.toLocaleString("ru-RU", {
        minimumFractionDigits: value % 1 ? 2 : 0,
        maximumFractionDigits: 2,
    });

    const formatOdd = (value) => toNumber(value, 0).toLocaleString("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });

    const formatTotal = () => {
        const coefficient = items.size
            ? [...items.values()].reduce((product, item) => product * toNumber(item.coefficient, 2), 1)
            : 0;
        const stake = toNumber(stakeInput?.value);
        if (coefficientNode) coefficientNode.textContent = formatOdd(coefficient);
        if (totalNode) totalNode.textContent = formatMoney(stake * coefficient);
    };

    const updateWalletBalance = (result) => {
        const display = result?.balance_display;
        if (!display) return;
        document.querySelectorAll("[data-wallet-balance]").forEach((node) => {
            node.textContent = `${display} ₽`;
        });
    };

    const updateConfidenceVisual = () => {
        const value = currentConfidence();
        if (confidenceInput) {
            confidenceInput.min = String(minConfidence);
        }
        if (confidenceInput && Number.parseInt(confidenceInput.value, 10) !== value) {
            confidenceInput.value = String(value);
        }
        if (confidenceValue) confidenceValue.textContent = `${value}%`;
        if (confidenceFill) confidenceFill.style.width = `${value}%`;
    };

    const readOdd = (value) => {
        const odd = toNumber(value, 0);
        return odd > 0 ? odd : 0;
    };

    const updateMatchButtons = () => {
        document.querySelectorAll("[data-match-bets]").forEach((group) => {
            const item = items.get(group.dataset.matchId);
            group.closest("[data-match-card]")?.classList.toggle("is-added", Boolean(item));
            group.querySelectorAll("[data-bet-option]").forEach((button) => {
                const isSameSelection = Boolean(item)
                    && item.market === button.dataset.market
                    && item.selection === button.dataset.selection;
                button.classList.toggle("is-active", isSameSelection);
                if (isSameSelection) item.betKey = button.dataset.betKey;
            });
        });
    };

    document.addEventListener("matches:appended", () => updateMatchButtons());

    const updateState = () => {
        root.classList.toggle("has-coupon", items.size > 0);
        if (countNode) countNode.textContent = `${items.size}/20`;
        if (submitButton) {
            submitButton.disabled = !canWrite || !couponIsComplete() || submitButton.classList.contains("is-loading");
        }
        updateConfidenceVisual();
        formatTotal();
        updateMatchButtons();
    };

    const buildItem = (group, option) => ({
        matchId: group.dataset.matchId,
        matchTitle: group.dataset.title,
        league: group.dataset.league,
        time: group.dataset.time,
        betKey: option.dataset.betKey,
        market: option.dataset.market,
        selection: option.dataset.selection,
        shortLabel: option.querySelector("span")?.textContent || option.dataset.selection,
        coefficient: readOdd(option.dataset.coefficient),
        lastSeen: group.dataset.lastSeen || "",
    });

    const normalizeDraftItem = (rawItem) => ({
        ...rawItem,
        matchId: String(rawItem.matchId),
        matchTitle: rawItem.matchTitle || rawItem.title || "",
        coefficient: readOdd(rawItem.coefficient),
        lastSeen: rawItem.lastSeen || "",
    });

    const updateCouponItem = (node, item) => {
        node.querySelector("[data-coupon-selection]").textContent = item.selection;
        node.querySelector("[data-coupon-short]").textContent = item.shortLabel;
        node.querySelector("[data-coupon-item-odd]").textContent = formatOdd(item.coefficient);
        const titleText = node.querySelector(".coupon-item-title strong");
        const metaText = node.querySelector(".coupon-item-title span");
        if (titleText) titleText.textContent = item.matchTitle;
        if (metaText) metaText.textContent = `${item.league} · ${item.time}`;
    };

    const saveLocalSnapshot = (dirty = true) => {
        if (!canWrite) return;
        const snapshot = {
            id: draftId,
            stake: stakeInput?.value || "",
            confidence: currentConfidence(),
            items: [...items.values()],
            dirty,
            savedAt: Date.now(),
        };
        try {
            if (!snapshot.items.length && !snapshot.stake) {
                localStorage.removeItem(storageKey);
            } else {
                localStorage.setItem(storageKey, JSON.stringify(snapshot));
            }
        } catch (error) {
            // Local storage is only a fast reload fallback; DB autosave remains primary.
        }
    };

    const renderItem = (item) => {
        const node = document.createElement("article");
        node.className = "coupon-item";
        node.dataset.couponMatchId = item.matchId;

        const top = document.createElement("div");
        top.className = "coupon-item-top";

        const match = document.createElement("div");
        match.className = "coupon-item-match";

        const ball = document.createElement("span");
        ball.className = "coupon-item-ball";
        ball.textContent = "Ф";

        const title = document.createElement("div");
        title.className = "coupon-item-title";
        const titleText = document.createElement("strong");
        const metaText = document.createElement("span");
        title.append(titleText, metaText);
        match.append(ball, title);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "coupon-remove";
        remove.setAttribute("aria-label", "Удалить из прогноза");
        remove.textContent = "×";
        remove.addEventListener("click", () => {
            items.delete(item.matchId);
            node.remove();
            updateState();
            saveLocalSnapshot(true);
            setNote(items.size ? "Изменения сохраняются..." : "Прогноз пуст.");
            syncDraft(false);
        });

        const actions = document.createElement("div");
        actions.className = "coupon-item-actions";

        const collapse = document.createElement("button");
        collapse.type = "button";
        collapse.className = "coupon-item-toggle";
        collapse.setAttribute("aria-label", "Свернуть игру");
        collapse.setAttribute("aria-expanded", "true");
        collapse.textContent = "⌃";
        collapse.addEventListener("click", () => {
            const isCollapsed = node.classList.toggle("is-collapsed");
            collapse.setAttribute("aria-expanded", String(!isCollapsed));
            collapse.setAttribute("aria-label", isCollapsed ? "Раскрыть игру" : "Свернуть игру");
        });

        actions.append(collapse, remove);
        top.append(match, actions);

        const pick = document.createElement("div");
        pick.className = "coupon-pick";
        pick.innerHTML = `
            <span data-coupon-short></span>
            <strong data-coupon-selection></strong>
            <small>кф <b data-coupon-item-odd></b></small>
        `;

        const body = document.createElement("div");
        body.className = "coupon-item-body";
        body.append(pick);

        node.append(top, body);
        itemsRoot.append(node);
        updateCouponItem(node, item);
        initScrollableNames(node);
    };

    const payloadFromState = (autosave) => ({
        coupon_id: draftId,
        autosave,
        stake: stakeInput?.value || "",
        confidence: currentConfidence(),
        items: [...items.values()].map((item) => ({
            match_id: item.matchId,
            market: item.market,
            selection: item.selection,
            coefficient: item.coefficient,
        })),
    });

    const applyServerDraft = (draft) => {
        if (!draft) {
            draftId = null;
            saveLocalSnapshot(false);
            return;
        }

        draftId = draft.id || draftId;
        if (confidenceInput) confidenceInput.value = String(normalizeConfidence(draft.confidence));
        const serverItems = new Map((draft.items || []).map((rawItem) => {
            const item = normalizeDraftItem(rawItem);
            return [String(item.matchId), item];
        }));
        items.forEach((item, matchId) => {
            const fresh = serverItems.get(String(matchId));
            if (fresh?.lastSeen) item.lastSeen = fresh.lastSeen;
        });
        updateConfidenceVisual();
        saveLocalSnapshot(false);
    };

    const clearCoupon = () => {
        draftId = null;
        items.clear();
        itemsRoot.replaceChildren();
        if (stakeInput) stakeInput.value = "";
        if (confidenceInput) confidenceInput.value = "50";
        try {
            localStorage.removeItem(storageKey);
        } catch (error) {
            // Local storage cleanup is best-effort.
        }
        updateState();
    };

    const responseError = (xhr, fallback) => {
        const data = xhr?.responseJSON;
        if (data?.error) return data.error;
        return fallback;
    };

    const setSubmitLoading = (isLoading, checking = false) => {
        if (!submitButton) return;
        submitButton.classList.toggle("is-loading", isLoading);
        submitButton.setAttribute("aria-busy", String(isLoading));
        if (submitStatus) {
            submitStatus.textContent = checking ? "Проверяем матчи..." : "Сохраняем...";
        }
        submitButton.disabled = isLoading || !couponIsComplete();
    };

    const syncDraft = (manual) => {
        if (!canWrite) return;
        if (!manual && !autosaveEnabled) return;
        if (!window.jQuery) {
            setNote("Не удалось загрузить модуль сохранения. Обновите страницу.", "error");
            if (manual) setSubmitLoading(false);
            return;
        }

        if (autosaveTimer) {
            window.clearTimeout(autosaveTimer);
            autosaveTimer = null;
        }

        if (manual) {
            if (autosaveRequest) {
                autosaveRequest.abort();
                autosaveRequest = null;
            }
            if (manualRequest) return;
        } else if (!items.size && !draftId) {
            return;
        }

        const request = window.jQuery.ajax({
            url: createUrl,
            method: "POST",
            data: JSON.stringify(payloadFromState(!manual)),
            contentType: "application/json; charset=UTF-8",
            dataType: "json",
            headers: {
                "X-CSRFToken": csrfInput.value,
            },
        });

        if (manual) {
            manualRequest = request;
        } else {
            if (autosaveRequest) autosaveRequest.abort();
            autosaveRequest = request;
        }

        request.done((result) => {
            if (!result?.ok) {
                setNote(result?.error || (manual ? "Не удалось сохранить прогноз." : "Не удалось сохранить купон."), "error");
                return;
            }
            if (manual) {
                updateWalletBalance(result);
                clearCoupon();
                setNote(result.message || "Прогноз опубликован.", "success");
            } else {
                draftId = result.draft_id || null;
                applyServerDraft(result.draft || null);
                if (items.size) {
                    setNote("Купон сохранен автоматически.", "success");
                }
            }
        });

        request.fail((xhr, statusText) => {
            if (statusText === "abort") return;
            setNote(
                responseError(xhr, manual ? "Не удалось сохранить прогноз." : "Не удалось сохранить купон."),
                "error"
            );
        });

        request.always(() => {
            if (manual) {
                manualRequest = null;
                setSubmitLoading(false);
            } else {
                autosaveRequest = null;
            }
            updateState();
        });
    };

    const scheduleDraftSync = () => {
        if (!canWrite || restoring) return;
        saveLocalSnapshot(true);
        if (autosaveTimer) window.clearTimeout(autosaveTimer);
        autosaveTimer = window.setTimeout(() => syncDraft(false), 500);
    };

    const itemNeedsRemoteCheck = (item) => {
        if (!item.lastSeen) return true;
        const seenAt = Date.parse(item.lastSeen);
        if (!Number.isFinite(seenAt)) return true;
        return Date.now() - seenAt > staleSeconds * 1000;
    };

    const upsertItem = (item) => {
        const existing = items.get(item.matchId);
        if (!existing && couponTypeRule === "single" && items.size >= 1) {
            items.clear();
            itemsRoot.replaceChildren();
        }
        if (!existing && items.size >= 20) {
            setNote("В одном прогнозе может быть максимум 20 игр.", "error");
            return;
        }

        if (existing) {
            Object.assign(existing, item);
            const node = itemsRoot.querySelector(`[data-coupon-match-id="${item.matchId}"]`);
            if (node) updateCouponItem(node, existing);
            setNote("Исход обновлен. Сохраняем купон...");
        } else {
            items.set(item.matchId, item);
            renderItem(item);
            setNote(couponTypeRule === "single" ? "Игра выбрана для одиночного прогноза." : "Игра добавлена в прогноз.");
        }

        if (sidebar && sidebar.classList.contains("is-collapsed")) {
            sidebar.classList.remove("is-collapsed");
            if (sidebarToggle) sidebarToggle.setAttribute("aria-expanded", "true");
        }

        updateState();
        saveLocalSnapshot(true);
        syncDraft(false);
        itemsRoot.scrollIntoView({ behavior: "smooth", block: "nearest" });
    };

    const restoreDraft = () => {
        let serverDraft = null;
        const script = document.getElementById("coupon-draft-data");
        if (script) {
            try {
                serverDraft = JSON.parse(script.textContent || "null");
            } catch (error) {
                serverDraft = null;
            }
        }

        let localDraft = null;
        try {
            localDraft = JSON.parse(localStorage.getItem(storageKey) || "null");
        } catch (error) {
            localDraft = null;
        }

        const localHasUnsavedChanges = Boolean(
            localDraft
            && localDraft.dirty === true
            && Array.isArray(localDraft.items)
            && localDraft.items.length
        );
        const draft = localHasUnsavedChanges ? localDraft : (serverDraft || localDraft);
        if (!draft || !Array.isArray(draft.items) || !draft.items.length) {
            restoring = false;
            updateState();
            return;
        }

        draftId = draft.id || null;
        if (stakeInput) stakeInput.value = draft.stake || "";
        if (confidenceInput) confidenceInput.value = String(normalizeConfidence(draft.confidence));

        draft.items.forEach((rawItem) => {
            const item = normalizeDraftItem(rawItem);
            items.set(item.matchId, item);
            renderItem(item);
        });

        restoring = false;
        updateState();
        saveLocalSnapshot(localHasUnsavedChanges);
        if (localHasUnsavedChanges) {
            setNote("Сохраняем последние изменения...", "success");
            syncDraft(false);
        } else {
            setNote("Купоны восстановлены.", "success");
        }
    };

    stakeInput?.addEventListener("input", () => {
        stakeInput.closest(".coupon-field")?.classList.toggle(
            "is-invalid",
            stakeInput.value.length > 0 && !hasPositiveStake()
        );
        updateState();
        scheduleDraftSync();
    });

    confidenceInput?.addEventListener("input", () => {
        updateConfidenceVisual();
        updateState();
        scheduleDraftSync();
    });

    root.addEventListener("click", (event) => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest("[data-bet-option]");
        if (!button || !root.contains(button)) return;
        const group = button.closest("[data-match-bets]");
        if (!group) return;
        upsertItem(buildItem(group, button));
    });

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!canWrite) {
            setNote("Сохранять прогнозы могут только эксперты.", "error");
            return;
        }
        if (items.size < 1 || items.size > 20) {
            setNote("В прогнозе должно быть от 1 до 20 игр.", "error");
            return;
        }
        if (couponTypeRule === "single" && items.size !== 1) {
            setNote("В этом турнире доступны только одиночные прогнозы.", "error");
            return;
        }
        if (couponTypeRule === "express" && items.size < 2) {
            setNote("В этом турнире доступны только экспрессы.", "error");
            return;
        }
        if (currentConfidence() < minConfidence) {
            setNote(`Минимальная уверенность для турнира — ${minConfidence}%.`, "error");
            return;
        }
        if (!couponIsComplete()) {
            setNote("Укажите сумму и общую уверенность в прогнозе.", "error");
            return;
        }

        saveLocalSnapshot(true);
        const checking = [...items.values()].some(itemNeedsRemoteCheck);
        setSubmitLoading(true, checking);
        setNote(checking ? "Проверяем актуальное состояние матчей..." : "Сохраняем прогноз...");
        syncDraft(true);
    });

    restoreDraft();
})();
