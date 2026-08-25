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
        scope.querySelectorAll(".match-league strong, .match-league small, .match-team strong, .coupon-item-title strong, .coupon-item-title span, .coupon-pick strong").forEach((node) => {
            if (node.dataset.scrollNameReady === "true") return;
            node.dataset.scrollNameReady = "true";
            node.addEventListener("mouseenter", () => startNameScroll(node));
            node.addEventListener("mouseleave", () => stopNameScroll(node));
            node.addEventListener("focus", () => startNameScroll(node));
            node.addEventListener("blur", () => stopNameScroll(node));
        });
    };

    initScrollableNames(root);

    const form = root.querySelector("[data-coupon-form]");
    if (!form) return;

    const itemsRoot = root.querySelector("[data-coupon-items]");
    const countNode = root.querySelector("[data-coupon-count]");
    const stakeInput = root.querySelector("[data-coupon-stake]");
    const commentInput = root.querySelector("[data-coupon-comment]");
    const coefficientNode = root.querySelector("[data-coupon-coefficient]");
    const totalNode = root.querySelector("[data-coupon-total]");
    const noteNode = root.querySelector("[data-coupon-note]");
    const submitButton = root.querySelector(".coupon-submit");
    const csrfInput = form.querySelector("[name=csrfmiddlewaretoken]");
    const canWrite = root.dataset.canWrite === "true";
    const createUrl = root.dataset.createUrl;
    const items = new Map();

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
        && [...items.values()].every((item) => item.selection.trim().length > 0)
    );

    const setNote = (message, state = "") => {
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
        coefficientNode.textContent = formatOdd(coefficient);
        totalNode.textContent = formatMoney(stake * coefficient);
    };

    const readOdd = (value) => {
        const odd = toNumber(value, 2);
        return odd > 0 ? odd : 2;
    };

    const updateState = () => {
        root.classList.toggle("has-coupon", items.size > 0);
        countNode.textContent = `${items.size}/5`;
        submitButton.disabled = !canWrite || !couponIsComplete();
        formatTotal();

        document.querySelectorAll("[data-match-bets]").forEach((group) => {
            const item = items.get(group.dataset.matchId);
            group.closest("[data-match-card]")?.classList.toggle("is-added", Boolean(item));
            group.querySelectorAll("[data-bet-option]").forEach((button) => {
                button.classList.toggle("is-active", Boolean(item) && item.betKey === button.dataset.betKey);
            });
        });
    };

    const buildItem = (group, option) => ({
        matchId: group.dataset.matchId,
        title: group.dataset.title,
        league: group.dataset.league,
        time: group.dataset.time,
        betKey: option.dataset.betKey,
        market: option.dataset.market,
        selection: option.dataset.selection,
        shortLabel: option.querySelector("span")?.textContent || option.dataset.selection,
        coefficient: readOdd(option.dataset.coefficient),
    });

    const updateCouponItem = (node, item) => {
        node.querySelector("[data-coupon-selection]").textContent = item.selection;
        node.querySelector("[data-coupon-short]").textContent = item.shortLabel;
        node.querySelector("[data-coupon-item-odd]").textContent = formatOdd(item.coefficient);
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
        titleText.textContent = item.title;
        const metaText = document.createElement("span");
        metaText.textContent = `${item.league} · ${item.time}`;
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
            if (items.size === 0) setNote(canWrite ? "Заполните сумму и общий комментарий к купону." : "Сохранять купоны могут только эксперты.");
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
            setNote("Ставка в купоне обновлена.");
        } else {
            items.set(item.matchId, item);
            renderItem(item);
            setNote(canWrite ? "Заполните сумму и общий комментарий к купону." : "Сохранять купоны могут только эксперты.");
        }

        if (sidebar && sidebar.classList.contains("is-collapsed")) {
            sidebar.classList.remove("is-collapsed");
            if (sidebarToggle) sidebarToggle.setAttribute("aria-expanded", "true");
        }

        updateState();
        itemsRoot.scrollIntoView({ behavior: "smooth", block: "nearest" });
    };

    stakeInput?.addEventListener("input", () => {
        stakeInput.closest(".coupon-field")?.classList.toggle("is-invalid", stakeInput.value.length > 0 && !hasPositiveStake());
        updateState();
    });

    commentInput?.addEventListener("input", () => {
        commentInput.closest(".coupon-field")?.classList.toggle("is-invalid", commentInput.value.length > 0 && !hasComment());
        updateState();
    });

    document.querySelectorAll("[data-bet-option]").forEach((button) => {
        button.addEventListener("click", () => {
            const group = button.closest("[data-match-bets]");
            if (!group) return;
            upsertItem(buildItem(group, button));
        });
    });

    form.addEventListener("submit", async (event) => {
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

        const payload = {
            title: form.elements.title.value,
            stake: stakeInput.value,
            comment: commentInput.value,
            items: [...items.values()].map((item) => ({
                match_id: item.matchId,
                market: item.market,
                selection: item.selection,
                coefficient: item.coefficient,
            })),
        };

        submitButton.disabled = true;
        setNote("Сохраняю купон...");

        try {
            const response = await fetch(createUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfInput.value,
                },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Не удалось сохранить купон.");
            }

            items.clear();
            itemsRoot.replaceChildren();
            form.reset();
            updateState();
            setNote(result.message, "success");
        } catch (error) {
            setNote(error.message, "error");
            updateState();
        }
    });

    updateState();
})();
