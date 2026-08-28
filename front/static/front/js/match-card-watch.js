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

    document.addEventListener("click", async (event) => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest("[data-match-watch-toggle]");
        if (!button) return;

        const url = button.dataset.watchUrl;
        if (!url || button.disabled) return;

        button.disabled = true;
        const previousState = button.classList.contains("is-watching");

        try {
            const response = await fetch(url, {
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
            const payload = contentType.includes("application/json")
                ? await response.json()
                : null;
            if (!response.ok || !payload?.ok) {
                throw new Error(payload?.error || "Не удалось обновить отслеживание");
            }

            setWatching(button, payload.watching);

            const currentScope = new URL(window.location.href).searchParams.get("scope") || "all";
            if (currentScope === "watched" && !payload.watching) {
                window.location.reload();
            }
        } catch (error) {
            setWatching(button, previousState);
        } finally {
            button.disabled = false;
        }
    });
})();
