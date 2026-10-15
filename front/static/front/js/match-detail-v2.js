(() => {
    const page = document.querySelector(".match-page-v2");
    if (!page) return;

    page.querySelectorAll(".match-v2-tabs a[href^='#']").forEach((link) => {
        link.addEventListener("click", (event) => {
            const target = page.querySelector(link.getAttribute("href"));
            if (!target) return;
            event.preventDefault();
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    });

    page.querySelectorAll("[data-match-v2-progress]").forEach((timeline) => {
        const value = Number(timeline.dataset.matchV2Progress || 0);
        const progress = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
        timeline.style.setProperty("--match-v2-progress", `${progress}%`);
    });

    const allOdds = page.querySelector("[data-match-v2-odds-all]");
    const revealAllOdds = () => {
        if (!allOdds) return;
        allOdds.hidden = false;
        page.querySelectorAll("[data-match-v2-odds-toggle]").forEach((toggle) => {
            toggle.setAttribute("aria-expanded", "true");
            toggle.textContent = "Скрыть исходы ↑";
        });
    };

    page.querySelectorAll("[data-match-v2-odds-toggle]").forEach((button) => {
        if (!allOdds) return;
        button.addEventListener("click", () => {
            const isOpen = allOdds.hidden;
            if (isOpen) {
                revealAllOdds();
            } else {
                allOdds.hidden = true;
                page.querySelectorAll("[data-match-v2-odds-toggle]").forEach((toggle) => {
                    toggle.setAttribute("aria-expanded", "false");
                    toggle.textContent = "Все исходы →";
                });
            }
            button.setAttribute("aria-expanded", String(isOpen));
        });
    });

    const eventsUrl = page.dataset.eventsUrl;
    const eventsPanel = page.querySelector("[data-match-events-panel]");
    if (!eventsUrl || !eventsPanel) return;

    const eventsList = eventsPanel.querySelector("[data-match-events-list]");
    const emptyState = eventsPanel.querySelector("[data-match-events-empty]");
    const emptyTitle = eventsPanel.querySelector("[data-match-events-empty-title]");
    const emptyText = eventsPanel.querySelector("[data-match-events-empty-text]");
    const statusText = eventsPanel.querySelector("[data-match-events-status]");
    const eventsCount = eventsPanel.querySelector("[data-match-events-count]");
    const retryButton = eventsPanel.querySelector("[data-match-events-retry]");
    const announcer = eventsPanel.querySelector("[data-match-events-announcer]");
    const matchStatus = page.querySelector("[data-match-status]");
    const matchStatusLabel = page.querySelector("[data-match-status-label]");
    const score = page.querySelector("[data-match-score]");
    const timeline = page.querySelector("[data-match-timeline]");
    const timelineProgress = timeline?.querySelector("progress");
    const timelineLabel = timeline?.querySelector("[data-match-timeline-label]");
    const initialKeys = Array.from(eventsList?.querySelectorAll("[data-event-key]") || []).map(
        (item) => item.dataset.eventKey,
    );
    let knownEventKeys = new Set(initialKeys);
    let currentVersion = "";
    let timer = null;
    let requestController = null;
    let requestSequence = 0;
    let failureCount = 0;

    const LIVE_INTERVAL = 15000;
    const PREMATCH_INTERVAL = 60000;
    const REFRESH_QUEUE_INTERVAL = 5000;
    const MAX_RETRY_INTERVAL = 60000;

    const localizedName = (value) => {
        if (!value || typeof value !== "object") return "";
        return String(value.name_ru || value.name || "").trim();
    };

    const eventKind = (item) => {
        const serverKind = item?.presentation?.kind;
        if (serverKind) return serverKind;
        const code = `${item?.type?.code || ""} ${item?.detail?.code || ""}`.toLowerCase();
        if (code.includes("yellow")) return "yellow-card";
        if (code.includes("red")) return "red-card";
        if (code.includes("goal")) return "goal";
        if (code.includes("penalty")) return "penalty";
        if (code.includes("substitut") || code.includes("change")) return "substitution";
        if (code.includes("var") || code.includes("video")) return "review";
        return "default";
    };

    const eventIcon = (item, kind) => {
        if (item?.presentation?.icon) return item.presentation.icon;
        return {
            goal: "⚽",
            "yellow-card": "▮",
            "red-card": "▮",
            penalty: "P",
            substitution: "↕",
            review: "VAR",
            default: "•",
        }[kind];
    };

    const eventSide = (item) => {
        const side = String(item?.presentation?.side || item?.team?.side || "").toLowerCase();
        if (["home", "team1", "1"].includes(side)) return "home";
        if (["away", "team2", "2"].includes(side)) return "away";
        return "neutral";
    };

    const appendText = (parent, tagName, text, className = "") => {
        if (!text) return null;
        const element = document.createElement(tagName);
        if (className) element.className = className;
        element.textContent = text;
        parent.append(element);
        return element;
    };

    const createEventItem = (item, isNew) => {
        const kind = eventKind(item);
        const side = eventSide(item);
        const row = document.createElement("li");
        row.className = `match-v2-event is-${side} is-${kind}${isNew ? " is-new" : ""}`;
        row.dataset.eventKey = String(item.key || item.id || "");
        row.dataset.eventMinute = item?.time?.minute ?? "";
        row.dataset.eventExtra = item?.time?.extra ?? "";

        const copy = document.createElement("div");
        copy.className = "match-v2-event-copy";
        copy.id = `match-event-${item.id}`;
        copy.setAttribute("role", "tooltip");
        const type = document.createElement("span");
        type.className = "match-v2-event-type";
        const icon = document.createElement("i");
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = eventIcon(item, kind);
        type.append(icon, document.createTextNode(localizedName(item.type) || "Событие"));
        copy.append(type);

        const participant = Array.isArray(item.participants)
            ? item.participants.find((entry) => localizedName(entry?.player))
            : null;
        const primaryName =
            localizedName(item.player) ||
            localizedName(participant?.player) ||
            localizedName(item.team) ||
            "Событие матча";
        appendText(copy, "strong", primaryName);

        const assistName = localizedName(item.assist);
        if (assistName) appendText(copy, "small", `Ассист: ${assistName}`);
        const detailName = localizedName(item.detail);
        if (detailName && detailName.toLowerCase() !== (localizedName(item.type) || "").toLowerCase()) {
            appendText(copy, "small", detailName);
        }

        const time = document.createElement("time");
        time.textContent = item?.time?.label || "—";
        const marker = document.createElement("button");
        marker.type = "button";
        marker.className = "match-v2-event-marker";
        marker.setAttribute("aria-describedby", copy.id);
        marker.setAttribute("aria-label", `${time.textContent} · ${localizedName(item.type) || 'Событие'} · ${primaryName}`);
        const markerIcon = document.createElement("i");
        markerIcon.setAttribute("aria-hidden", "true");
        markerIcon.textContent = eventIcon(item, kind);
        marker.append(markerIcon, time);
        row.append(marker, copy);
        return row;
    };

    const positionEventTooltip = row => {
        if (!row || row.hidden) return;
        const marker = row.querySelector('.match-v2-event-marker');
        const copy = row.querySelector('.match-v2-event-copy');
        const rect = marker.getBoundingClientRect();
        const below = window.innerHeight - rect.bottom - 16;
        const above = rect.top - 16;
        const upwards = below < 120 && above > below;
        const height = Math.max(60, Math.min(280, upwards ? above : below));
        row.style.setProperty('--tooltip-height', `${height}px`);
        row.style.setProperty('--tooltip-top', upwards
            ? `${-Math.min(copy.scrollHeight, height) - 6}px`
            : `${rect.height + 6}px`);
    };

    const layoutEvents = () => {
        const rows = Array.from(eventsList.querySelectorAll('[data-event-key]:not([data-event-group])'))
            .sort((a, b) => (Number(a.dataset.eventMinute === '' ? Infinity : a.dataset.eventMinute)
                - Number(b.dataset.eventMinute === '' ? Infinity : b.dataset.eventMinute))
                || Number(a.dataset.eventExtra || 0) - Number(b.dataset.eventExtra || 0));
        const duration = Number(eventsPanel.dataset.eventDuration) || 90;
        const total = Math.max(duration, ...rows.map(row => Number(row.dataset.eventMinute) || 0));
        const width = eventsList.clientWidth;
        if (!width) return;
        const focusedKey = document.activeElement?.closest('[data-event-key]')?.dataset.eventKey;
        const openKey = eventsList.querySelector('.is-open')?.dataset.eventKey;
        eventsList.querySelectorAll('[data-event-group]').forEach(row => row.remove());
        const minutes = new Map();
        rows.forEach((row) => {
            const minute = Number(row.dataset.eventMinute);
            const hasMinute = row.dataset.eventMinute !== '' && Number.isFinite(minute);
            const key = hasMinute ? minute : 'unknown';
            if (!minutes.has(key)) minutes.set(key, {
                position: hasMinute ? Math.max(22, Math.min(width - 22, width * minute / total)) : width - 22,
                rows: [],
            });
            minutes.get(key).rows.push(row);
        });
        const lanes = [-Infinity, -Infinity];
        const groups = [];
        for (const group of minutes.values()) {
            const lane = lanes.findIndex(end => group.position - end >= 44);
            if (lane < 0) {
                // Both rows are occupied: absorb the events into the closest
                // existing marker rather than growing a third row.
                const closest = groups.reduce((a, b) =>
                    Math.abs(a.position - group.position) <= Math.abs(b.position - group.position) ? a : b);
                closest.rows.push(...group.rows);
            } else {
                group.lane = lane;
                lanes[lane] = group.position;
                groups.push(group);
            }
        }
        const fragment = document.createDocumentFragment();
        for (const group of groups) {
            const members = group.rows;
            let row = members[0];
            if (members.length > 1) {
                row = document.createElement('li');
                row.className = `match-v2-event is-group${members.some(member => member.classList.contains('is-new')) ? ' is-new' : ''}`;
                row.dataset.eventGroup = '';
                row.dataset.eventKey = members[0].dataset.eventKey;
                row.dataset.eventKeys = JSON.stringify(members.map(member => member.dataset.eventKey));
                const marker = members[0].querySelector('.match-v2-event-marker').cloneNode(true);
                const copy = document.createElement('div');
                copy.className = 'match-v2-event-copy';
                copy.id = `${marker.getAttribute('aria-describedby')}-group`;
                copy.setAttribute('role', 'tooltip');
                copy.tabIndex = 0;
                copy.setAttribute('aria-label', 'События группы');
                marker.setAttribute('aria-describedby', copy.id);
                marker.setAttribute('aria-label', `События: ${members.length} · ${members[0].querySelector('time').textContent} — ${members.at(-1).querySelector('time').textContent}`);
                marker.querySelector('i').textContent = '⋯';
                const count = appendText(marker, 'span', String(members.length), 'match-v2-event-count');
                count.setAttribute('aria-hidden', 'true');
                members.forEach(member => {
                    const entry = document.createElement('div');
                    entry.className = 'match-v2-event-group-entry';
                    appendText(entry, 'time', member.querySelector('time').textContent);
                    member.querySelector('.match-v2-event-copy').childNodes.forEach(node => entry.append(node.cloneNode(true)));
                    copy.append(entry);
                    member.hidden = true;
                });
                row.append(marker, copy);
            } else {
                row.hidden = false;
            }
            if (members.some(member => member.dataset.eventKey === openKey)) row.classList.add('is-open');
            const position = group.position;
            row.style.setProperty('--event-position', `${position}px`);
            row.style.setProperty('--event-lane', group.lane);
            const tooltipWidth = Math.min(220, width);
            const tooltipLeft = Math.max(0, Math.min(width - tooltipWidth, position - tooltipWidth / 2));
            row.style.setProperty('--tooltip-offset', `${tooltipLeft - position}px`);
            fragment.append(row);
        }
        // Keep the untouched source nodes for regrouping after a resize.
        rows.filter(row => row.hidden).forEach(row => fragment.append(row));
        eventsList.replaceChildren(fragment);
        Array.from(eventsList.children).forEach(positionEventTooltip);
        if (focusedKey) {
            Array.from(eventsList.children).find(row => !row.hidden && (
                row.dataset.eventKey === focusedKey || JSON.parse(row.dataset.eventKeys || '[]').includes(focusedKey)
            ))?.querySelector('.match-v2-event-marker')?.focus({ preventScroll: true });
        }
    };

    eventsList.addEventListener('click', (event) => {
        const marker = event.target.closest('.match-v2-event-marker');
        if (!marker) return;
        const row = marker.closest('[data-event-key]');
        const wasOpen = row.classList.contains('is-open');
        eventsList.querySelectorAll('.is-open').forEach(item => item.classList.remove('is-open'));
        row.classList.toggle('is-open', !wasOpen);
        row.classList.remove('is-dismissed');
    });
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        eventsList.querySelectorAll('[data-event-key]').forEach(row => {
            row.classList.remove('is-open');
            row.classList.add('is-dismissed');
        });
    });
    eventsList.addEventListener('pointerover', event => {
        const row = event.target.closest('[data-event-key]');
        row?.classList.remove('is-dismissed');
        positionEventTooltip(row);
    });
    eventsList.addEventListener('focusin', event => positionEventTooltip(event.target.closest('[data-event-key]')));
    window.addEventListener('scroll', () => {
        eventsList.querySelectorAll('.is-open, :scope > li:hover, :scope > li:focus-within').forEach(positionEventTooltip);
    }, { passive: true });
    document.addEventListener('click', event => {
        if (!eventsList.contains(event.target)) {
            eventsList.querySelectorAll('.is-open').forEach(row => row.classList.remove('is-open'));
        }
    });
    new ResizeObserver(layoutEvents).observe(eventsList);
    layoutEvents();

    const stateCopy = (state, scope, hasEvents) => {
        if (state === "pending") {
            return ["Ожидаем данные", "Ожидаем начало матча", "События появятся здесь после стартового свистка."];
        }
        if (state === "unavailable") {
            return [
                hasEvents ? "Архив событий" : "Нет данных",
                "Хронология недоступна",
                "Поставщик не передаёт события для этого матча.",
            ];
        }
        if (state === "invalid") {
            return ["Ожидаем данные", "Ожидаем данные", "Источник ещё не подтвердил доступность хронологии."];
        }
        if (state === "empty") {
            return [
                "Событий пока нет",
                "Событий пока нет",
                "Как только что-то произойдёт, хронология обновится автоматически.",
            ];
        }
        return [scope === "live" ? "Обновляется автоматически" : "Хронология матча", "Событий пока нет", "Хронология матча обновляется автоматически."];
    };

    const updatePanelState = (payload, itemCount) => {
        const state = payload.events_state?.status || "invalid";
        eventsPanel.hidden = state === 'unavailable' && itemCount === 0;
        eventsPanel.dataset.eventsState = state;
        eventsPanel.classList.remove("is-pending", "is-unavailable", "is-invalid", "is-empty", "is-ready", "is-error");
        eventsPanel.classList.add(`is-${state}`);
        const [status, title, description] = stateCopy(state, payload.match?.scope, itemCount > 0);
        statusText.textContent = status;
        emptyTitle.textContent = title;
        emptyText.textContent = description;
    };

    const updateEvents = (payload) => {
        const focusedKey = document.activeElement?.closest('[data-event-key]')?.dataset.eventKey;
        const openKey = eventsList.querySelector('.is-open')?.dataset.eventKey;
        const items = Array.isArray(payload.events) ? payload.events : [];
        const nextKeys = new Set(items.map((item) => String(item.key || item.id || "")));
        const newItems = currentVersion
            ? items.filter((item) => !knownEventKeys.has(String(item.key || item.id || "")))
            : [];
        const fragment = document.createDocumentFragment();
        items.forEach((item) => {
            const key = String(item.key || item.id || "");
            const row = createEventItem(item, currentVersion !== "" && !knownEventKeys.has(key));
            if (key === openKey) row.classList.add('is-open');
            fragment.append(row);
        });
        eventsList.replaceChildren(fragment);
        eventsList.hidden = items.length === 0;
        emptyState.hidden = items.length > 0;
        eventsCount.textContent = String(items.length);
        layoutEvents();
        if (focusedKey) {
            Array.from(eventsList.children).find(row => !row.hidden && (row.dataset.eventKey === focusedKey
                || JSON.parse(row.dataset.eventKeys || '[]').includes(focusedKey)))
                ?.querySelector('.match-v2-event-marker')?.focus({ preventScroll: true });
        }

        if (newItems.length) {
            const latest = newItems[newItems.length - 1];
            const label = localizedName(latest.player) || localizedName(latest.type) || "событие матча";
            announcer.textContent = `Новое событие: ${latest?.time?.label || ""} ${label}`.trim();
        }
        knownEventKeys = nextKeys;
    };

    const updateScore = (match) => {
        if (!match || !score) return;
        const home = match.score?.home;
        const away = match.score?.away;
        if (home !== null && home !== undefined && away !== null && away !== undefined) {
            const previous = score.textContent.replace(/\s/g, "");
            const next = `${home}:${away}`;
            if (previous !== next) {
                const homeValue = document.createElement("span");
                const separator = document.createElement("i");
                const awayValue = document.createElement("span");
                homeValue.dataset.matchScoreHome = "";
                awayValue.dataset.matchScoreAway = "";
                homeValue.textContent = home;
                separator.textContent = ":";
                awayValue.textContent = away;
                score.replaceChildren(homeValue, separator, awayValue);
                score.classList.remove("is-updated");
                void score.offsetWidth;
                score.classList.add("is-updated");
            }
        }

        if (matchStatus && matchStatusLabel) {
            const scope = match.scope || "prematch";
            matchStatus.classList.remove("match-status-prematch", "match-status-live", "match-status-finished");
            matchStatus.classList.add(`match-status-${scope}`);
            matchStatusLabel.textContent = match.status || "";
            const liveDot = matchStatus.querySelector(".match-live-dot");
            if (scope === "live" && !liveDot) {
                const dot = document.createElement("i");
                dot.className = "match-live-dot";
                dot.setAttribute("aria-hidden", "true");
                matchStatus.prepend(dot);
            } else if (scope !== "live" && liveDot) {
                liveDot.remove();
            }
        }

        if (timeline && timelineProgress && timelineLabel) {
            const progress = Math.max(0, Math.min(100, Number(match.progress) || 0));
            const shouldShow = match.scope === "live" || (match.scope === "finished" && knownEventKeys.size > 0);
            timeline.hidden = !shouldShow;
            timeline.dataset.matchV2Progress = String(progress);
            timeline.style.setProperty("--match-v2-progress", `${progress}%`);
            timelineProgress.value = progress;
            timelineProgress.textContent = `${progress}%`;
            timelineLabel.textContent = match.timeline_label || "";
            timelineLabel.hidden = !match.timeline_label;
        }
    };

    const clearTimer = () => {
        if (timer !== null) window.clearTimeout(timer);
        timer = null;
    };

    const schedule = (payload = null) => {
        clearTimer();
        if (document.hidden || !navigator.onLine) return;
        const scope = payload?.match?.scope || "prematch";
        const state = payload?.events_state;
        if (scope === "finished" && !state?.stale && !state?.refresh_queued) return;
        const delay = state?.refresh_queued
            ? REFRESH_QUEUE_INTERVAL
            : scope === "live"
                ? LIVE_INTERVAL
                : PREMATCH_INTERVAL;
        timer = window.setTimeout(refresh, delay);
    };

    const showRequestError = () => {
        eventsPanel.classList.add("is-error");
        statusText.textContent = navigator.onLine ? "Не удалось обновить" : "Нет соединения";
        retryButton.hidden = false;
    };

    async function refresh() {
        clearTimer();
        if (document.hidden || !navigator.onLine) {
            if (!navigator.onLine) showRequestError();
            return;
        }
        requestController?.abort();
        requestController = new AbortController();
        const sequence = ++requestSequence;
        eventsPanel.setAttribute("aria-busy", "true");
        eventsPanel.classList.add("is-refreshing");
        retryButton.hidden = true;

        try {
            const response = await fetch(eventsUrl, {
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: requestController.signal,
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            if (!payload.ok || sequence !== requestSequence) return;
            failureCount = 0;
            updatePanelState(payload, Array.isArray(payload.events) ? payload.events.length : 0);
            if (payload.version !== currentVersion) {
                updateEvents(payload);
                updateScore(payload.match);
                currentVersion = payload.version || "";
            }
            schedule(payload);
        } catch (error) {
            if (error.name === "AbortError") return;
            failureCount += 1;
            showRequestError();
            const delay = Math.min(5000 * 2 ** (failureCount - 1), MAX_RETRY_INTERVAL);
            timer = window.setTimeout(refresh, delay);
        } finally {
            if (sequence === requestSequence) {
                eventsPanel.removeAttribute("aria-busy");
                eventsPanel.classList.remove("is-refreshing");
            }
        }
    }

    retryButton.addEventListener("click", refresh);
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            clearTimer();
            requestController?.abort();
        } else {
            refresh();
        }
    });
    window.addEventListener("online", refresh);
    window.addEventListener("offline", () => {
        clearTimer();
        requestController?.abort();
        showRequestError();
    });
    window.addEventListener("pagehide", () => {
        clearTimer();
        requestController?.abort();
    });

    refresh();
})();
