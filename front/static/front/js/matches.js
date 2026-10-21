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
    const freePredictionInput = root.querySelector("[data-coupon-free-prediction]");
    const freePredictionLabel = root.querySelector("[data-coupon-free-prediction-label]");
    const confidenceInput = root.querySelector("[data-coupon-confidence]");
    const confidenceValue = root.querySelector("[data-coupon-confidence-value]");
    const confidenceFill = root.querySelector("[data-coupon-confidence-fill]");
    const coefficientNode = root.querySelector("[data-coupon-coefficient]");
    const totalNode = root.querySelector("[data-coupon-total]");
    const noteNode = root.querySelector("[data-coupon-note]");
    const submitButton = root.querySelector("[data-coupon-submit]");
    const submitStatus = root.querySelector("[data-coupon-submit-status]");
    const richAction = root.querySelector("[data-coupon-rich-action]");
    const csrfInput = form.querySelector("[name=csrfmiddlewaretoken]");
    const canWrite = root.dataset.canWrite === "true";
    const createUrl = root.dataset.createUrl;
    const staleSeconds = Number.parseInt(root.dataset.staleSeconds || "60", 10) || 60;
    const autosaveEnabled = root.dataset.autosave !== "false";
    const tournamentSelect = form.querySelector("[data-coupon-tournament]");
    const submitLabel = submitButton?.querySelector(".coupon-submit-label");
    const richUrl = form.dataset.richUrl || "";
    // A tournament chosen in the coupon sets its rules; such coupons are published as rich predictions.
    const activeTournament = () => window.CappersCouponTournament?.current() || null;
    const minConfidenceOf = () => Math.max(0, Math.min(100, activeTournament()?.min_confidence || 0));
    const couponTypeRuleOf = () => activeTournament()?.coupon_type || "any";
    const sharedDraft = autosaveEnabled ? window.CappersCouponDraft : null;
    const items = new Map();

    let draftId = null;
    let autosaveTimer = null;
    let autosaveRequest = null;
    let manualRequest = null;
    let restoring = true;
    let editVersion = 0;
    let syncGeneration = 0;
    let dirty = false;
    let renderedRevision = null;

    const toNumber = (value, fallback = 0) => {
        const parsed = Number.parseFloat(String(value ?? "").replace(",", "."));
        return Number.isFinite(parsed) ? parsed : fallback;
    };

    const normalizeConfidence = (value) => {
        const parsed = Number.parseInt(String(value ?? "50"), 10);
        if (!Number.isFinite(parsed)) return Math.max(50, minConfidenceOf());
        return Math.max(minConfidenceOf(), Math.min(100, parsed));
    };

    const currentConfidence = () => normalizeConfidence(confidenceInput?.value);
    const hasPositiveStake = () => {
        const stake = toNumber(stakeInput?.value);
        return Number.isInteger(stake) && stake > 0;
    };
    const useFreePrediction = () => Boolean(freePredictionInput?.checked);
    const freePredictionStake = Number.parseInt(freePredictionInput?.dataset.freePredictionStake || "", 10) || 0;
    let manualStake = "";

    // A free prediction always plays the stake from the roulette settings; the server ignores the typed one.
    const syncFreePredictionStake = () => {
        if (!stakeInput || !freePredictionStake) return;
        const locked = useFreePrediction();
        if (locked && !stakeInput.readOnly) {
            manualStake = stakeInput.value;
            stakeInput.value = String(freePredictionStake);
        } else if (!locked && stakeInput.readOnly) {
            stakeInput.value = manualStake;
        }
        stakeInput.readOnly = locked;
        stakeInput.dispatchEvent(new Event("input", { bubbles: true }));
    };

    const couponCountMatchesRule = () => {
        if (items.size < 1 || items.size > 20) return false;
        if (couponTypeRuleOf() === "single") return items.size === 1;
        if (couponTypeRuleOf() === "express") return items.size >= 2;
        return true;
    };

    const tournamentProblems = () => [...items.values()].filter((item) => (
        window.CappersCouponTournament?.problems(item).length
    )).length;

    // A tournament coupon only needs valid positions here: stake, text and the rest are set in the editor.
    const tournamentCouponReady = () => couponCountMatchesRule() && !tournamentProblems();

    const couponIsComplete = () => (
        couponCountMatchesRule()
        && hasPositiveStake()
        && currentConfidence() >= minConfidenceOf()
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

    const formatCoins = (value) => Math.round(value).toLocaleString("ru-RU", {
        maximumFractionDigits: 0,
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
        if (totalNode) totalNode.textContent = formatCoins(stake * coefficient);
    };

    const updateWalletBalance = (result) => {
        const display = result?.coin_balance_display;
        if (!display) return;
        document.querySelectorAll("[data-wallet-balance]").forEach((node) => {
            node.dataset.walletBalanceVisible = display;
            if (node.textContent.trim() === node.dataset.walletBalanceMasked) return;
            node.textContent = display;
        });
    };

    const updateFreePredictionBalance = (result) => {
        if (!freePredictionInput) return;
        const remaining = Number(result?.free_predictions_remaining);
        if (!Number.isFinite(remaining)) return;

        freePredictionInput.dataset.freePredictionsCount = String(Math.max(0, remaining));
        if (remaining <= 0) {
            freePredictionInput.checked = false;
            freePredictionInput.disabled = true;
            freePredictionInput.closest(".coupon-free-option")?.setAttribute("hidden", "");
        }
        if (freePredictionLabel) {
            freePredictionLabel.textContent = remaining > 0
                ? `Доступно: ${remaining}. Ставка — ${freePredictionStake} коинов, коины не спишутся.`
                : "Бесплатные прогнозы закончились.";
        }
    };

    const updateConfidenceVisual = () => {
        const value = currentConfidence();
        if (confidenceInput) {
            confidenceInput.min = String(minConfidenceOf());
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
                const isSameSelection = Boolean(item) && sameOutcome(
                    item,
                    button.dataset.market,
                    button.dataset.outcomeCode,
                    button.dataset.selection,
                );
                button.classList.toggle("is-active", isSameSelection);
                if (isSameSelection) item.betKey = button.dataset.betKey;
            });
        });
    };

    document.addEventListener("matches:appended", () => updateMatchButtons());

    const updateState = () => {
        root.classList.toggle("has-coupon", items.size > 0);
        if (countNode) countNode.textContent = `${items.size}/20`;
        const tournament = activeTournament();
        if (submitButton) {
            const ready = tournament ? tournamentCouponReady() : couponIsComplete();
            submitButton.disabled = !canWrite || !ready || submitButton.classList.contains("is-loading");
        }
        if (submitLabel) submitLabel.textContent = tournament ? "Перейти к расширенному прогнозу" : "Сделать прогноз";
        form.classList.toggle("is-tournament-coupon", Boolean(tournament));
        window.CappersCouponTournament?.markItems();
        if (richAction) {
            richAction.hidden = items.size < 1 || !draftId;
        }
        updateConfidenceVisual();
        formatTotal();
        updateMatchButtons();
    };

    const buildItem = (group, option) => ({
        matchId: group.dataset.matchId,
        sport: group.closest("[data-match-sport]")?.dataset.matchSport || "",
        matchTitle: group.dataset.title,
        league: group.dataset.league,
        time: group.dataset.time,
        startsAt: group.closest("[data-match-starts-at]")?.dataset.matchStartsAt || "",
        betKey: option.dataset.betKey,
        market: option.dataset.market,
        selection: option.dataset.selection,
        outcomeCode: option.dataset.outcomeCode || "",
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
        node.dataset.sport = item.sport || "";
        node.dataset.coefficient = String(item.coefficient);
        node.dataset.startsAt = item.startsAt || "";
        node.querySelector("[data-coupon-selection]").textContent = item.selection;
        node.querySelector("[data-coupon-short]").textContent = item.shortLabel;
        node.querySelector("[data-coupon-item-odd]").textContent = formatOdd(item.coefficient);
        const titleText = node.querySelector(".coupon-item-title strong");
        const metaText = node.querySelector(".coupon-item-title span");
        if (titleText) titleText.textContent = item.matchTitle;
        if (metaText) metaText.textContent = `${item.league} · ${item.time}`;
    };

    const sameSelection = (left, right) => (
        String(left || "").trim().toLowerCase() === String(right || "").trim().toLowerCase()
    );

    // An outcome is identified by its code; the text is only compared for old drafts without a code.
    const sameOutcome = (item, market, outcomeCode, selection) => {
        if (item.market !== market) return false;
        if (item.outcomeCode && outcomeCode) return item.outcomeCode === outcomeCode;
        return sameSelection(item.selection, selection);
    };

    const refreshMatchButtonOdd = (item, coefficient) => {
        const value = toNumber(coefficient, 0).toFixed(2);
        document.querySelectorAll(`[data-match-bets][data-match-id="${item.matchId}"] [data-bet-option]`).forEach((button) => {
            if (!sameOutcome(item, button.dataset.market, button.dataset.outcomeCode, button.dataset.selection)) return;
            const previous = button.dataset.coefficient;
            const oddNode = [...button.querySelectorAll("strong, small, b")]
                .find((node) => node.textContent.trim() === previous);
            if (oddNode) oddNode.textContent = value;
            button.dataset.coefficient = value;
        });
    };

    // The server always takes the coefficient from the current line; keep the coupon in sync with it.
    const applyItemOdds = (matchId, market, selection, coefficient, outcomeCode = "") => {
        const item = items.get(String(matchId));
        const odd = readOdd(coefficient);
        if (!item || !odd || !sameOutcome(item, market, outcomeCode, selection)) return false;
        if (!item.outcomeCode && outcomeCode) item.outcomeCode = outcomeCode;
        refreshMatchButtonOdd(item, odd);
        if (item.coefficient === odd) return false;
        item.coefficient = odd;
        const node = itemsRoot.querySelector(`[data-coupon-match-id="${item.matchId}"]`);
        if (node) updateCouponItem(node, item);
        return true;
    };

    const markDraftChanged = (changed = true) => {
        if (changed) { ++editVersion; dirty = true; }
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
            markDraftChanged(true);
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
        ...(sharedDraft ? { base_revision: sharedDraft.get()?.revision || null } : {}),
        autosave,
        stake: stakeInput?.value || "",
        confidence: currentConfidence(),
        use_free_prediction: useFreePrediction(),
        audience: "free",
        tournament_id: activeTournament()?.id || null,
        items: [...items.values()].map((item) => ({
            match_id: item.matchId,
            market: item.market,
            selection: item.selection,
            outcome_code: item.outcomeCode || "",
            coefficient: item.coefficient,
        })),
    });

    const applyServerDraft = (draft) => {
        if (!draft) {
            replaceCanonicalDraft(null);
            return;
        }

        draftId = draft.id || draftId;
        renderedRevision = draft.revision || null;
        if (confidenceInput) confidenceInput.value = String(normalizeConfidence(draft.confidence));
        const serverItems = new Map((draft.items || []).map((rawItem) => {
            const item = normalizeDraftItem(rawItem);
            return [String(item.matchId), item];
        }));
        let oddsUpdated = false;
        items.forEach((item, matchId) => {
            const fresh = serverItems.get(String(matchId));
            if (fresh?.lastSeen) item.lastSeen = fresh.lastSeen;
            if (fresh && applyItemOdds(matchId, fresh.market, fresh.selection, fresh.coefficient, fresh.outcomeCode)) {
                oddsUpdated = true;
            }
        });
        updateConfidenceVisual();
        markDraftChanged(false);
        return oddsUpdated;
    };

    const clearCoupon = () => {
        draftId = null;
        items.clear();
        itemsRoot.replaceChildren();
        if (stakeInput) {
            stakeInput.value = "";
            stakeInput.readOnly = false;
        }
        manualStake = "";
        if (freePredictionInput) freePredictionInput.checked = false;
        if (confidenceInput) confidenceInput.value = "50";
        dirty = false;
        renderedRevision = null;
        sharedDraft?.accept(null);
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
            if (autosaveRequest) return autosaveRequest.then(() => syncDraft(true), () => setSubmitLoading(false));
            if (manualRequest) return manualRequest;
        } else if (autosaveRequest) {
            return autosaveRequest;
        } else if (!items.size && !draftId) {
            dirty = false;
            return;
        }

        const sentVersion = editVersion;
        const generation = syncGeneration;
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
            autosaveRequest = request;
        }

        request.done((result) => {
            if (generation !== syncGeneration) { sharedDraft?.refresh(); return; }
            if (!result?.ok) {
                setNote(result?.error || (manual ? "Не удалось сохранить прогноз." : "Не удалось сохранить купон."), "error");
                return;
            }
            if (manual) {
                updateWalletBalance(result);
                updateFreePredictionBalance(result);
                clearCoupon();
                setNote(result.message || "Прогноз опубликован.", "success");
            } else {
                draftId = result.draft_id || null;
                renderedRevision = result.draft?.revision || null;
                sharedDraft?.accept(result.draft || null);
                dirty = sentVersion !== editVersion;
                const oddsUpdated = dirty ? false : applyServerDraft(result.draft || null);
                if (oddsUpdated) {
                    setNote("Коэффициенты в купоне обновлены по текущей линии.");
                } else if (items.size) {
                    setNote("Купон сохранен автоматически.", "success");
                }
            }
        });

        request.fail((xhr, statusText) => {
            if (statusText === "abort") return;
            if (xhr?.responseJSON?.draft_conflict) {
                sharedDraft?.accept(xhr.responseJSON.draft || null, { broadcast: false });
                replaceCanonicalDraft(xhr.responseJSON.draft || null);
            }
            const oddsChanged = xhr?.responseJSON?.odds_changed;
            if (Array.isArray(oddsChanged) && oddsChanged.length) {
                oddsChanged.forEach((change) => {
                    applyItemOdds(change.match_id, change.market, change.selection, change.coefficient, change.outcome_code);
                });
                markDraftChanged(true);
            }
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
                if (generation === syncGeneration && sentVersion !== editVersion && dirty) {
                    syncDraft(false);
                }
            }
            updateState();
        });
        return request;
    };

    const scheduleDraftSync = () => {
        if (!canWrite || restoring) return;
        markDraftChanged(true);
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
        if (!existing && couponTypeRuleOf() === "single" && items.size >= 1) {
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
            setNote(couponTypeRuleOf() === "single" ? "Игра выбрана для одиночного прогноза." : "Игра добавлена в прогноз.");
        }

        if (sidebar && sidebar.classList.contains("is-collapsed")) {
            sidebar.classList.remove("is-collapsed");
            if (sidebarToggle) sidebarToggle.setAttribute("aria-expanded", "true");
        }

        updateState();
        markDraftChanged(true);
        syncDraft(false);
        itemsRoot.scrollIntoView({ behavior: "smooth", block: "nearest" });
    };

    // The draft keeps the tournament picked in another tab or page.
    // A saved draft decides the tournament, including "none" set in another tab or a tournament that is over.
    // Without a draft the current choice (e.g. from a tournament page link) stays.
    let linkedTournament = new URLSearchParams(window.location.search).get("tournament") || "";
    const restoreTournament = (draft) => {
        if (!tournamentSelect || !draft) return;
        const hasOption = (value) => [...tournamentSelect.options].some((option) => option.value === value);
        // A tournament page link wins over the draft once, then gets saved into it.
        const saved = linkedTournament && hasOption(linkedTournament) ? linkedTournament : String(draft.tournament_id || "");
        linkedTournament = "";
        const value = hasOption(saved) ? saved : "";
        // The change event also saves the choice when the draft holds another (or an ended) tournament.
        if (tournamentSelect.value === value && String(draft.tournament_id || "") === value) return;
        tournamentSelect.value = value;
        tournamentSelect.dispatchEvent(new Event("change", { bubbles: true }));
    };

    const replaceCanonicalDraft = (draft) => {
        ++syncGeneration;
        if (autosaveTimer) { window.clearTimeout(autosaveTimer); autosaveTimer = null; }
        dirty = false;
        draftId = draft?.id || null;
        renderedRevision = draft?.revision || null;
        items.clear();
        itemsRoot.replaceChildren();
        if (stakeInput) stakeInput.value = draft?.stake || "";
        if (freePredictionInput) freePredictionInput.checked = false;
        syncFreePredictionStake();
        if (confidenceInput) confidenceInput.value = String(normalizeConfidence(draft?.confidence));
        (draft?.items || []).forEach((rawItem) => {
            const item = normalizeDraftItem(rawItem);
            items.set(item.matchId, item);
            renderItem(item);
        });
        restoring = false;
        restoreTournament(draft);
        updateState();
    };

    const restoreDraft = () => {
        let draft = sharedDraft?.get();
        if (!sharedDraft) {
            try { draft = JSON.parse(document.getElementById("coupon-draft-data")?.textContent || "null"); }
            catch (_error) { draft = null; }
        }
        replaceCanonicalDraft(draft);
        if (draft) setNote("Купон восстановлен.", "success");
    };
    window.addEventListener("coupon:draft-changed", (event) => {
        if (!sharedDraft) return;
        const draft = event.detail.draft;
        if ((draft?.id || null) === draftId && (draft?.revision || null) === renderedRevision) return;
        replaceCanonicalDraft(draft);
        setNote(draft ? "Купон обновлён." : "Купон пуст.");
    });
    const openRichEditor = async (url) => {
        try {
            markDraftChanged(true);
            while (dirty || autosaveRequest) {
                const request = autosaveRequest || syncDraft(false);
                if (!request) break;
                const result = await request;
                if (!result?.ok) return;
            }
            if (!dirty && draftId && items.size) window.location.assign(url);
        } catch (_error) { setNote("Не удалось сохранить купон. Повторите переход после сохранения.", "error"); }
    };

    richAction?.addEventListener("click", (event) => {
        if (!sharedDraft) return;
        event.preventDefault();
        openRichEditor(richAction.href);
    });

    tournamentSelect?.addEventListener("change", () => {
        updateState();
        scheduleDraftSync();
    });
    window.addEventListener("coupon:tournament-changed", () => updateState());

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

    freePredictionInput?.addEventListener("change", () => {
        syncFreePredictionStake();
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
        if (activeTournament()) {
            if (tournamentProblems()) {
                setNote("Уберите из купона отмеченные красным матчи — они не подходят турниру.", "error");
                return;
            }
            if (!couponCountMatchesRule()) {
                setNote(couponTypeRuleOf() === "single" ? "В этом турнире доступны только одиночные прогнозы." : "Добавьте матчи: в этом турнире нужны экспрессы.", "error");
                return;
            }
            setNote("Сохраняем купон и открываем расширенный прогноз...");
            openRichEditor(richUrl);
            return;
        }
        if (items.size < 1 || items.size > 20) {
            setNote("В прогнозе должно быть от 1 до 20 игр.", "error");
            return;
        }
        if (couponTypeRuleOf() === "single" && items.size !== 1) {
            setNote("В этом турнире доступны только одиночные прогнозы.", "error");
            return;
        }
        if (couponTypeRuleOf() === "express" && items.size < 2) {
            setNote("В этом турнире доступны только экспрессы.", "error");
            return;
        }
        if (currentConfidence() < minConfidenceOf()) {
            setNote(`Минимальная уверенность для турнира — ${minConfidenceOf()}%.`, "error");
            return;
        }
        if (!couponIsComplete()) {
            setNote("Укажите целое количество коинов и общую уверенность в прогнозе.", "error");
            return;
        }

        markDraftChanged(true);
        const checking = [...items.values()].some(itemNeedsRemoteCheck);
        setSubmitLoading(true, checking);
        setNote(checking ? "Проверяем актуальное состояние матчей..." : "Сохраняем прогноз...");
        syncDraft(true);
    });

    restoreDraft();
})();
