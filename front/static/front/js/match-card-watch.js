(() => {
    const formatLiveMinute = (value) => {
        const raw = String(value || "")
            .trim()
            .replace(/[’']/g, "′")
            .replace(/\s+/g, "");
        if (!raw) return "";
        if (raw.endsWith("′")) return raw;
        return `${raw}′`;
    };

    const baseMinute = (value) => {
        const match = String(value || "").match(/\d{1,3}/);
        return match ? Number.parseInt(match[0], 10) : null;
    };

    const formatLiveStatus = (status) => {
        if (!status) return;
        const label = status.querySelector("span");
        if (!label) return;

        const raw = label.textContent.trim();
        if (!raw) return;

        const pieces = raw.split(/\s+-\s+/);
        let phaseRaw = "";
        let minuteRaw = "";

        if (pieces.length > 1) {
            phaseRaw = pieces.shift().trim();
            minuteRaw = pieces.join("-").trim();
        } else if (/\d/.test(raw)) {
            minuteRaw = raw;
        } else {
            phaseRaw = raw;
        }

        const minute = baseMinute(minuteRaw);
        const phase = phaseRaw.toLowerCase().replace(/\s+/g, "");
        let period = "";

        if (["1", "1h", "1t", "1т", "first", "firsthalf"].includes(phase)) {
            period = "1Т";
        } else if (["2", "2h", "2t", "2т", "second", "secondhalf"].includes(phase)) {
            period = "2Т";
        } else if (["ht", "half", "halftime", "перерыв"].includes(phase)) {
            label.textContent = "Перерыв";
            return;
        } else if (["3", "et", "aet", "extra", "extratime"].includes(phase)) {
            period = "Extra";
        } else if (minute !== null) {
            if (minute <= 45) period = "1Т";
            else if (minute <= 90) period = "2Т";
            else period = "Extra";
        }

        const minuteLabel = formatLiveMinute(minuteRaw);
        if (period === "Extra") {
            label.textContent = minuteLabel ? `Extra ${minuteLabel}` : "Extra";
        } else if (period) {
            label.textContent = minuteLabel ? `${period} - ${minuteLabel}` : period;
        } else if (minuteLabel) {
            label.textContent = `LIVE - ${minuteLabel}`;
        } else {
            label.textContent = "LIVE";
        }
    };

    const formatLiveStatuses = (scope = document) => {
        if (scope.matches?.(".match-status-live")) formatLiveStatus(scope);
        scope.querySelectorAll?.(".match-status-live").forEach(formatLiveStatus);
    };

    formatLiveStatuses(document);
    document.addEventListener("matches:appended", (event) => {
        (event.detail?.nodes || []).forEach((node) => formatLiveStatuses(node));
    });

    const initOddsAccordion = (scope = document) => {
        const panels = [];
        if (scope.matches?.(".match-odds-panel")) panels.push(scope);
        scope.querySelectorAll?.(".match-odds-panel").forEach((panel) => panels.push(panel));

        panels.forEach((panel) => {
            if (panel.dataset.oddsAccordionReady === "true") return;
            panel.dataset.oddsAccordionReady = "true";

            const body = document.createElement("div");
            body.className = "match-odds-accordion-body";
            const inner = document.createElement("div");
            inner.className = "match-odds-accordion-inner";

            while (panel.firstChild) inner.appendChild(panel.firstChild);
            body.appendChild(inner);

            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "match-odds-accordion-toggle";
            toggle.setAttribute("aria-expanded", "true");
            toggle.setAttribute("aria-label", "Свернуть коэффициенты");
            toggle.title = "Свернуть коэффициенты";
            toggle.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 15 6-6 6 6"></path></svg>';

            panel.classList.toggle("has-odds-topbar", Boolean(inner.querySelector(".odds-topbar")));
            panel.append(toggle, body);

            toggle.addEventListener("click", () => {
                const collapsed = panel.classList.toggle("is-odds-collapsed");
                toggle.setAttribute("aria-expanded", String(!collapsed));
                const label = collapsed ? "Раскрыть коэффициенты" : "Свернуть коэффициенты";
                toggle.setAttribute("aria-label", label);
                toggle.title = label;
            });
        });
    };

    initOddsAccordion(document);
    document.addEventListener("matches:appended", (event) => {
        (event.detail?.nodes || []).forEach((node) => initOddsAccordion(node));
    });

    const loadMatchPredictionsScript = () => {
        if (!document.querySelector(".match-detail-page")) return;
        if (document.querySelector("script[data-match-predictions-script]")) return;

        const source = Array.from(document.scripts).find((script) =>
            /\/match-card-watch\.js(?:\?.*)?$/.test(script.src || ""),
        );
        if (!source?.src) return;

        const src = new URL(source.src);
        src.pathname = src.pathname.replace(/match-card-watch\.js$/, "match-predictions.js");
        src.search = "";

        const script = document.createElement("script");
        script.src = src.toString();
        script.dataset.matchPredictionsScript = "true";
        script.async = false;
        document.body.appendChild(script);
    };

    loadMatchPredictionsScript();

    const getCookie = (name) => {
        const cookies = document.cookie ? document.cookie.split(";") : [];
        for (const cookie of cookies) {
            const trimmed = cookie.trim();
            if (trimmed.startsWith(`${name}=`)) {
                return decodeURIComponent(trimmed.slice(name.length + 1));
            }
        }
        return "";
    };

    const setWatching = (button, watching) => {
        const active = Boolean(watching);
        button.classList.toggle("is-watching", active);
        button.setAttribute("aria-pressed", String(active));
        button.setAttribute("aria-label", active ? "Не отслеживать матч" : "Отслеживать матч");
        button.title = active ? "Матч отслеживается" : "Следить за матчем";
        button.closest(".match-watch-card-shell")?.classList.toggle("is-watched", active);
    };

    const currentDate = () => {
        const pageUrl = new URL(window.location.href);
        const fromUrl = pageUrl.searchParams.get("date");
        if (fromUrl) return fromUrl;
        const dateScript = document.querySelector("[data-match-date-filter]");
        return dateScript?.dataset.selectedDate || "";
    };

    const requestUrl = (rawUrl) => {
        const url = new URL(rawUrl, window.location.origin);
        const selectedDate = currentDate();
        if (selectedDate) url.searchParams.set("date", selectedDate);
        return `${url.pathname}${url.search}`;
    };

    const updateWatchTabCount = (count) => {
        if (!Number.isFinite(Number(count))) return;
        const counter = document.querySelector(".is-watch-tab b");
        if (!counter) return;
        counter.textContent = String(Number(count));
        counter.animate?.(
            [
                { transform: "scale(1)", color: "currentColor" },
                { transform: "scale(1.18)", color: "var(--yellow)" },
                { transform: "scale(1)", color: "currentColor" },
            ],
            { duration: 260, easing: "ease-out" },
        );
    };

    const scopeOrder = (scope) => ({ live: 0, prematch: 1, finished: 2 }[scope] ?? 3);

    const sortGridLive = () => {
        const grid = document.querySelector("[data-matches-grid]");
        if (!grid) return;
        const nodes = Array.from(grid.querySelectorAll(":scope > [data-match-shell-id]"));
        if (nodes.length < 2) return;

        const before = new Map(nodes.map((node) => [node, node.getBoundingClientRect()]));
        nodes.sort((left, right) => {
            const watchedDiff = Number(!left.classList.contains("is-watched")) - Number(!right.classList.contains("is-watched"));
            if (watchedDiff) return watchedDiff;
            const scopeDiff = scopeOrder(left.dataset.matchScope) - scopeOrder(right.dataset.matchScope);
            if (scopeDiff) return scopeDiff;
            const leftTime = Date.parse(left.dataset.matchStartsAt || "") || Number.MAX_SAFE_INTEGER;
            const rightTime = Date.parse(right.dataset.matchStartsAt || "") || Number.MAX_SAFE_INTEGER;
            if (leftTime !== rightTime) return leftTime - rightTime;
            return Number(left.dataset.matchShellId || 0) - Number(right.dataset.matchShellId || 0);
        });
        nodes.forEach((node) => grid.appendChild(node));

        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
        requestAnimationFrame(() => {
            nodes.forEach((node) => {
                const oldRect = before.get(node);
                const newRect = node.getBoundingClientRect();
                if (!oldRect) return;
                const dx = oldRect.left - newRect.left;
                const dy = oldRect.top - newRect.top;
                if (!dx && !dy) return;
                node.animate(
                    [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "translate(0, 0)" }],
                    { duration: 320, easing: "cubic-bezier(.2,.8,.2,1)" },
                );
            });
        });
    };

    document.addEventListener("click", async (event) => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest("[data-match-watch-toggle]");
        if (!button) return;

        const url = button.dataset.watchUrl;
        if (!url || button.disabled) return;

        button.disabled = true;
        const previousState = button.classList.contains("is-watching");
        const shell = button.closest(".match-watch-card-shell");

        try {
            const response = await fetch(requestUrl(url), {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                headers: {
                    Accept: "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            const contentType = response.headers.get("content-type") || "";
            const payload = contentType.includes("application/json") ? await response.json() : null;
            if (!response.ok || !payload?.ok) {
                throw new Error(payload?.error || "Не удалось обновить отслеживание");
            }

            setWatching(button, payload.watching);
            updateWatchTabCount(payload.watched_count);
            sortGridLive();

            document.dispatchEvent(
                new CustomEvent("matches:watch-changed", {
                    detail: {
                        watching: Boolean(payload.watching),
                        watchedCount: Number(payload.watched_count || 0),
                        matchId: shell?.dataset.matchShellId || "",
                    },
                }),
            );
        } catch (error) {
            setWatching(button, previousState);
        } finally {
            button.disabled = false;
        }
    });
})();
