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
    const commentInput = root.querySelector("[data-coupon-comment]");
    const coefficientNode = root.querySelector("[data-coupon-coefficient]");
    const totalNode = root.querySelector("[data-coupon-total]");
    const noteNode = root.querySelector("[data-coupon-note]");
    const submitButton = root.querySelector("[data-coupon-submit]");
    const submitStatus = root.querySelector("[data-coupon-submit-status]");
    const csrfInput = form.querySelector("[name=csrfmiddlewaretoken]");
    const canWrite = root.dataset.canWrite === "true";
    const createUrl = root.dataset.createUrl;
    const staleSeconds = Number.parseInt(root.dataset.staleSeconds || "60", 10) || 60;
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
        const parsed = Number.parseFloat(String(value || "").replace(",", "."));
        return Number.isFinite(parsed) ? parsed : fallback;
    };

    const hasPositiveStake = () => toNumber(stakeInput?.value) > 0;
    const hasComment = () => (commentInput?.value || "").trim().length > 0;

    const couponIsComplete = () => (
        items.size > 0
        && items.size <= 5
        && hasPositiveStake()
        && hasComment()
        && [...items.values()].every((item) => String(item.selection || "").trim().length > 0)
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

    const formatOdd = (value) => toNumber(value, 2).toLocaleString("ru-RU", {
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

    const readOdd = (value) => {
        const odd = toNumber(value, 2);
        return odd > 0 ? odd : 2;
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

    const updateState = () => {
        root.classList.toggle("has-coupon", items.size > 0);
        if (countNode) countNode.textContent = `${items.size}/5`;
        if (submitButton) {
            submitButton.disabled = !canWrite || !couponIsComplete() || submitButton.classList.contains("is-loading");
        }
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
            comment: commentInput?.value || "",
            items: [...items.values()],
            dirty,
            savedAt: Date.now(),
        };
        try {
            if (!snapshot.items.length && !snapshot.stake && !snapshot.comment) {
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
        remove.setAttribute("aria-label", "Удалить из купона");
        remove.textContent = "×";
        remove.addEventListener("click", () => {
            items.delete(item.matchId);
            node.remove();
            updateState();
            saveLocalSnapshot(true);
            setNote(items.size ? "Изменения сохраняются..." : "Купон пуст.");
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
        comment: commentInput?.value || "",
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
        const serverItems = new Map((draft.items || []).map((rawItem) => {
            const item = normalizeDraftItem(rawItem);
            return [String(item.matchId), item];
        }));
        items.forEach((item, matchId) => {
            const fresh = serverItems.get(String(matchId));
            if (fresh?.lastSeen) item.lastSeen = fresh.lastSeen;
        });
        saveLocalSnapshot(false);
    };

    const clearCoupon = () => {
        draftId = null;
        items.clear();
        itemsRoot.replaceChildren();
        if (stakeInput) stakeInput.value = "";
        if (commentInput) commentInput.value = "";
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
                setNote(result?.error || (manual ? "Не удалось сохранить купон." : "Не удалось сохранить черновик."), "error");
                return;
            }
            if (manual) {
                clearCoupon();
                setNote(result.message || "Прогноз опубликован.", "success");
            } else {
                draftId = result.draft_id || null;
                applyServerDraft(result.draft || null);
                if (items.size) {
                    setNote("Черновик сохранен автоматически.", "success");
                }
            }
        });

        request.fail((xhr, statusText) => {
            if (statusText === "abort") return;
            setNote(
                responseError(xhr, manual ? "Не удалось сохранить купон." : "Не удалось сохранить черновик."),
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
        if (!existing && items.size >= 5) {
            setNote("В одном купоне может быть максимум 5 игр.", "error");
            return;
        }

        if (existing) {
            Object.assign(existing, item);
            const node = itemsRoot.querySelector(`[data-coupon-match-id="${item.matchId}"]`);
            if (node) updateCouponItem(node, existing);
            setNote("Ставка в купоне обновлена. Сохраняем черновик...");
        } else {
            items.set(item.matchId, item);
            renderItem(item);
            setNote("Игра добавлена. Сохраняем черновик...");
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
        stakeInput.value = draft.stake || "";
        commentInput.value = draft.comment || "";

        draft.items.forEach((rawItem) => {
            const item = normalizeDraftItem(rawItem);
            items.set(item.matchId, item);
            renderItem(item);
        });

        restoring = false;
        updateState();
        saveLocalSnapshot(localHasUnsavedChanges);
        if (localHasUnsavedChanges) {
            setNote("Черновик восстановлен. Сохраняем последние изменения...", "success");
            syncDraft(false);
        } else {
            setNote("Черновик восстановлен из базы.", "success");
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

    commentInput?.addEventListener("input", () => {
        commentInput.closest(".coupon-field")?.classList.toggle(
            "is-invalid",
            commentInput.value.length > 0 && !hasComment()
        );
        updateState();
        scheduleDraftSync();
    });

    document.querySelectorAll("[data-bet-option]").forEach((button) => {
        button.addEventListener("click", () => {
            const group = button.closest("[data-match-bets]");
            if (!group) return;
            upsertItem(buildItem(group, button));
        });
    });

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!canWrite) {
            setNote("Сохранять купоны могут только эксперты.", "error");
            return;
        }
        if (items.size < 1 || items.size > 5) {
            setNote("В купоне должно быть от 1 до 5 игр.", "error");
            return;
        }
        if (!couponIsComplete()) {
            setNote("Заполните сумму и общий комментарий к купону.", "error");
            return;
        }

        saveLocalSnapshot(true);
        const checking = [...items.values()].some(itemNeedsRemoteCheck);
        setSubmitLoading(true, checking);
        setNote(checking ? "Проверяем актуальное состояние матчей..." : "Сохраняем купон...");
        syncDraft(true);
    });

    restoreDraft();
})();
