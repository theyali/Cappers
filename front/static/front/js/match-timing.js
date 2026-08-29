(() => {
    const endpoint = window.CAPPERS_MATCH_TIMING_URL || "/games/timing/";
    const cache = new Map();
    let refreshTimer = null;
    let scanTimer = null;
    let requestInFlight = false;

    const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
    });
    const dateYearFormatter = new Intl.DateTimeFormat("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
    });

    const cleanFormattedDate = (value) => String(value || "")
        .replace(",", "")
        .replace(/\s+/g, " ")
        .trim();

    const formatShortDate = (date) => cleanFormattedDate(dateFormatter.format(date));
    const formatFullDate = (date) => cleanFormattedDate(dateYearFormatter.format(date));

    const parseDate = (value) => {
        if (!value) return null;
        const date = new Date(value);
        return Number.isFinite(date.getTime()) ? date : null;
    };

    const formatCountdown = (seconds) => {
        const safe = Math.max(0, Math.floor(Number(seconds) || 0));
        const hours = Math.floor(safe / 3600);
        const minutes = Math.floor((safe % 3600) / 60);
        const secs = safe % 60;
        const mm = String(minutes).padStart(2, "0");
        const ss = String(secs).padStart(2, "0");
        return hours > 0 ? `${String(hours).padStart(2, "0")}:${mm}:${ss}` : `${mm}:${ss}`;
    };

    const visibleMatchIds = () => {
        const ids = new Set();
        document.querySelectorAll("[data-match-card][data-match-id], [data-match-bets][data-match-id], [data-coupon-match-id]").forEach((node) => {
            const value = node.dataset.matchId || node.dataset.couponMatchId;
            if (/^\d+$/.test(String(value || ""))) ids.add(String(value));
        });
        return [...ids];
    };

    const localizePredictionTimes = (scope = document) => {
        scope.querySelectorAll(".prediction-league-row time[datetime]").forEach((node) => {
            const date = parseDate(node.getAttribute("datetime"));
            if (date) node.textContent = formatShortDate(date);
        });
        scope.querySelectorAll(".prediction-published-at time[datetime]").forEach((node) => {
            const date = parseDate(node.getAttribute("datetime"));
            if (date) node.textContent = formatFullDate(date);
        });
    };

    const lockGroup = (group, message = "Матч уже начался — ставки закрыты") => {
        if (!group) return;
        group.classList.add("is-timing-locked", "is-locked");
        group.setAttribute("aria-label", message);
        group.querySelectorAll("[data-bet-option]").forEach((button) => {
            button.removeAttribute("data-bet-option");
            button.disabled = true;
            button.setAttribute("aria-disabled", "true");
            button.title = message;
        });
    };

    const setStatus = (node, state, text) => {
        if (!node || node.dataset.providerLive === "true") return;
        node.classList.remove("match-status-prematch", "match-status-countdown", "match-status-soon");
        node.classList.add(state === "soon" ? "match-status-soon" : "match-status-countdown");
        if (node.textContent !== text) node.textContent = text;
    };

    const updateCouponMeta = (matchId, startDate) => {
        const localTime = formatShortDate(startDate);
        document.querySelectorAll(`[data-coupon-match-id="${matchId}"] .coupon-item-title span`).forEach((meta) => {
            if (!meta.dataset.timingPrefix) {
                const current = meta.textContent || "";
                const separator = current.lastIndexOf(" · ");
                meta.dataset.timingPrefix = separator >= 0 ? current.slice(0, separator) : current;
            }
            const prefix = meta.dataset.timingPrefix || "";
            const next = prefix ? `${prefix} · ${localTime}` : localTime;
            if (meta.textContent !== next) meta.textContent = next;
        });
    };

    const renderTiming = (matchId, timing) => {
        if (!timing) return;
        const startDate = parseDate(timing.starts_at);
        const groups = document.querySelectorAll(`[data-match-bets][data-match-id="${matchId}"]`);

        if (timing.scope !== "prematch" || !timing.prediction_open) {
            groups.forEach((group) => lockGroup(
                group,
                timing.scope === "finished"
                    ? "Матч завершен — ставки закрыты"
                    : "Матч уже начался — ставки закрыты"
            ));
        }

        if (!startDate) return;
        const seconds = Math.ceil((startDate.getTime() - Date.now()) / 1000);
        const soonWindow = Math.max(0, Number(timing.soon_window_seconds) || 600);
        const isPrematch = timing.scope === "prematch";
        const isSoon = isPrematch && seconds <= soonWindow;
        const hasStartedLocally = isPrematch && seconds <= 0;

        document.querySelectorAll(`[data-match-card][data-match-id="${matchId}"]`).forEach((card) => {
            const dateNode = card.querySelector(".match-score [data-starts-at]");
            if (dateNode) dateNode.textContent = formatShortDate(startDate);

            if (isPrematch) {
                const statusNode = card.querySelector(".match-card-head .match-status");
                if (hasStartedLocally) {
                    setStatus(statusNode, "soon", "Скоро начнется");
                } else if (isSoon) {
                    setStatus(statusNode, "soon", `Скоро начнется · ${formatCountdown(seconds)}`);
                } else {
                    setStatus(statusNode, "countdown", `До начала · ${formatCountdown(seconds)}`);
                }
            }
        });

        groups.forEach((group) => {
            const page = group.closest(".match-detail-page");
            if (!page) return;
            const dateNode = page.querySelector(".match-detail-score span");
            if (dateNode && timing.scope === "prematch") {
                dateNode.textContent = formatFullDate(startDate);
            }
            const statusNode = page.querySelector(".match-detail-head .match-status");
            if (isPrematch) {
                if (hasStartedLocally) {
                    setStatus(statusNode, "soon", "Скоро начнется");
                } else if (isSoon) {
                    setStatus(statusNode, "soon", `Скоро начнется · ${formatCountdown(seconds)}`);
                } else {
                    setStatus(statusNode, "countdown", `До начала · ${formatCountdown(seconds)}`);
                }
            }
            if (hasStartedLocally) lockGroup(group);
        });

        updateCouponMeta(matchId, startDate);
    };

    const renderAll = () => {
        cache.forEach((timing, matchId) => renderTiming(matchId, timing));
        localizePredictionTimes(document);
    };

    const fetchTimings = async (force = false) => {
        if (requestInFlight) return;
        const ids = visibleMatchIds().filter((id) => force || !cache.has(id));
        if (!ids.length) return;

        requestInFlight = true;
        try {
            const url = new URL(endpoint, window.location.origin);
            url.searchParams.set("ids", ids.join(","));
            const response = await fetch(url.toString(), {
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (!response.ok) return;
            const data = await response.json();
            if (!data?.ok || !data.matches) return;
            Object.entries(data.matches).forEach(([matchId, timing]) => cache.set(String(matchId), timing));
            renderAll();
        } catch (error) {
            // Server-side validation still prevents predictions after kickoff.
        } finally {
            requestInFlight = false;
        }
    };

    const scheduleScan = () => {
        if (scanTimer) window.clearTimeout(scanTimer);
        scanTimer = window.setTimeout(() => {
            localizePredictionTimes(document);
            fetchTimings(false);
            renderAll();
        }, 40);
    };

    const start = () => {
        localizePredictionTimes(document);
        fetchTimings(false);
        window.setInterval(renderAll, 1000);
        refreshTimer = window.setInterval(() => fetchTimings(true), 30000);

        document.addEventListener("matches:appended", scheduleScan);
        const observer = new MutationObserver((mutations) => {
            if (mutations.some((mutation) => mutation.addedNodes.length)) scheduleScan();
        });
        observer.observe(document.body, { childList: true, subtree: true });

        window.addEventListener("pageshow", () => {
            fetchTimings(true);
            renderAll();
        });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
        start();
    }
})();
