// Shared section visits also run in the Mini App, without a desktop bell/menu.
(() => {
    const configNode = document.getElementById("notification-section-visit");
    if (!configNode) return;
    const config = JSON.parse(configNode.textContent || "null");
    if (!config) return;

    let revision = 0;
    let queue = Promise.resolve();
    const pending = new Map();
    let currentSection = config.section || "";
    if (config.profile_sections.length) {
        const activeTab = document.querySelector("[data-profile-tab-panel].is-active")?.dataset.profileTabPanel;
        currentSection = config.profile_sections.includes(activeTab) ? activeTab : "";
    }
    let needsRead = Boolean(currentSection);

    const sync = (payload = {}) => {
        if (payload.section_badges) {
            document.querySelectorAll("[data-notification-section-badge]").forEach((dot) => {
                dot.classList.toggle("is-empty", !payload.section_badges[dot.dataset.notificationSectionBadge]);
            });
            document.querySelectorAll("[data-notification-any-section]").forEach((dot) => {
                dot.classList.toggle("is-empty", !Object.values(payload.section_badges).some(Boolean));
            });
        }
        if (Object.prototype.hasOwnProperty.call(payload, "unread_count")) {
            const count = Math.max(0, Number.parseInt(payload.unread_count, 10) || 0);
            document.querySelectorAll("[data-notification-badge]").forEach((badge) => {
                badge.textContent = count > 99 ? "99+" : String(count);
                badge.classList.toggle("is-empty", count === 0);
            });
            document.querySelectorAll("[data-notification-nav]").forEach((nav) => {
                nav.setAttribute("aria-label", count ? `Уведомления, непрочитанных: ${count}` : "Уведомления");
            });
        }
    };

    const markSectionRead = (section) => {
        const url = config.urls?.[section];
        if (!url) return Promise.resolve(false);
        if (pending.has(section)) return pending.get(section);
        const task = queue.then(async () => {
            revision += 1;
            try {
                const token = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith("csrftoken="));
                const response = await fetch(url, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "X-CSRFToken": token ? decodeURIComponent(token.slice("csrftoken=".length)) : "",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                const payload = await response.json().catch(() => null);
                return response.ok && payload?.ok ? payload : null;
            } catch (error) {
                return null;
            } finally {
                revision += 1;
            }
        }).then((payload) => {
            if (!payload) return false;
            sync(payload);
            window.dispatchEvent(new Event("cappers:notifications-changed"));
            return true;
        }).finally(() => pending.delete(section));
        pending.set(section, task);
        queue = task.catch(() => false);
        return task;
    };

    const readCurrentSection = () => {
        if (!needsRead || document.hidden) return;
        const section = currentSection;
        needsRead = false;
        markSectionRead(section).then((ok) => {
            if (!ok && currentSection === section) needsRead = true;
        });
    };

    window.CappersNotifications = { sync, markSectionRead, revision: () => revision };
    window.addEventListener("profile:tab-activated", (event) => {
        const tab = event.detail?.tab || "";
        currentSection = config.profile_sections.includes(tab) ? tab : "";
        needsRead = Boolean(currentSection);
        readCurrentSection();
    });
    document.addEventListener("visibilitychange", readCurrentSection);
    window.addEventListener("online", readCurrentSection);
    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            needsRead = Boolean(currentSection);
            readCurrentSection();
        }
    });
    readCurrentSection();
})();

(() => {
    const nav = document.querySelector("[data-notification-nav]");
    if (!nav) return;

    const badges = document.querySelectorAll("[data-notification-badge]");
    const summaryUrl = nav.dataset.summaryUrl;
    const soundUrl = nav.dataset.soundUrl;
    const userId = nav.dataset.userId || "user";
    if (!summaryUrl) return;

    const cursorKey = `cappers.notifications.cursor.${userId}`;
    const savedCursor = Number.parseInt(sessionStorage.getItem(cursorKey) || "", 10);
    let cursorId = Number.isFinite(savedCursor) ? savedCursor : null;
    let inFlight = false;
    let timer = null;

    const audio = soundUrl ? new Audio(soundUrl) : null;
    let audioUnlocked = false;
    if (audio) {
        audio.preload = "auto";
        audio.volume = 0.58;
    }

    const removeUnlockListeners = () => {
        document.removeEventListener("pointerdown", unlockAudio, true);
        document.removeEventListener("touchstart", unlockAudio, true);
        document.removeEventListener("keydown", unlockAudio, true);
    };

    const unlockAudio = () => {
        if (!audio || audioUnlocked) return;
        const previousMuted = audio.muted;
        audio.muted = true;
        audio.currentTime = 0;
        const promise = audio.play();
        if (!promise || typeof promise.then !== "function") {
            audio.muted = previousMuted;
            return;
        }
        promise.then(() => {
            audio.pause();
            audio.currentTime = 0;
            audio.muted = previousMuted;
            audioUnlocked = true;
            removeUnlockListeners();
        }).catch(() => {
            audio.muted = previousMuted;
        });
    };

    if (audio) {
        document.addEventListener("pointerdown", unlockAudio, true);
        document.addEventListener("touchstart", unlockAudio, true);
        document.addEventListener("keydown", unlockAudio, true);
    }

    const playSound = () => {
        if (!audio) return;
        audio.currentTime = 0;
        audio.play().then(() => {
            audioUnlocked = true;
            removeUnlockListeners();
        }).catch(() => {});
    };

    const setBadge = (count) => {
        const safeCount = Math.max(0, Number.parseInt(count, 10) || 0);
        badges.forEach((badge) => {
            badge.textContent = safeCount > 99 ? "99+" : String(safeCount);
            badge.classList.toggle("is-empty", safeCount === 0);
        });
        nav.setAttribute(
            "aria-label",
            safeCount ? `Уведомления, непрочитанных: ${safeCount}` : "Уведомления"
        );
    };

    const setSectionBadges = (sectionBadges = {}) => {
        document.querySelectorAll("[data-notification-section-badge]").forEach((dot) => {
            const section = dot.dataset.notificationSectionBadge || "";
            dot.classList.toggle("is-empty", !sectionBadges[section]);
        });
    };

    const getToastStack = () => {
        let stack = document.querySelector("[data-notification-toast-stack]");
        if (stack) return stack;
        stack = document.createElement("div");
        stack.className = "notification-toast-stack";
        if (document.querySelector(".fixed-tg-btn-wrapper")) {
            stack.classList.add("has-fixed-telegram");
        }
        stack.dataset.notificationToastStack = "";
        stack.setAttribute("aria-live", "polite");
        stack.setAttribute("aria-atomic", "false");
        document.body.appendChild(stack);
        return stack;
    };

    const removeToast = (toast) => {
        if (!toast || toast.classList.contains("is-leaving")) return;
        toast.classList.add("is-leaving");
        toast.classList.remove("is-visible");
        window.setTimeout(() => toast.remove(), 420);
    };

    const showToast = (notification) => {
        const stack = getToastStack();
        const toast = document.createElement("div");
        toast.className = "notification-toast";
        toast.setAttribute("role", "status");
        toast.dataset.notificationId = String(notification.id || "");

        let visual;
        if (notification.image_url) {
            visual = document.createElement("img");
            visual.className = "notification-toast-image";
            visual.src = notification.image_url;
            visual.alt = "";
            visual.width = 46;
            visual.height = 46;
            visual.loading = "lazy";
        } else {
            visual = document.createElement("span");
            visual.className = "notification-toast-icon";
            visual.setAttribute("aria-hidden", "true");
            visual.innerHTML = '<svg viewBox="0 0 24 24"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"></path><path d="M10 21h4"></path></svg>';
        }

        const copy = document.createElement("span");
        copy.className = "notification-toast-copy";
        const title = document.createElement("strong");
        title.textContent = notification.title || "Новое уведомление";
        const message = document.createElement("span");
        message.textContent = notification.message || "Откройте центр уведомлений, чтобы посмотреть подробнее.";
        copy.append(title, message);

        const close = document.createElement("button");
        close.type = "button";
        close.className = "notification-toast-close";
        close.setAttribute("aria-label", "Закрыть уведомление");
        close.textContent = "×";
        close.addEventListener("click", (event) => {
            event.stopPropagation();
            removeToast(toast);
        });

        toast.append(visual, copy, close);
        toast.addEventListener("click", () => {
            window.location.href = notification.url || nav.getAttribute("href") || "/notifications/";
        });
        stack.prepend(toast);

        requestAnimationFrame(() => {
            requestAnimationFrame(() => toast.classList.add("is-visible"));
        });

        window.setTimeout(() => removeToast(toast), 6200);
    };

    const persistCursor = () => {
        if (cursorId === null) return;
        sessionStorage.setItem(cursorKey, String(cursorId));
    };

    const scheduleNext = () => {
        window.clearTimeout(timer);
        const delay = document.hidden ? 15000 : 5000;
        timer = window.setTimeout(() => poll(), delay);
    };

    const poll = async ({ immediate = false } = {}) => {
        if (inFlight) return;
        inFlight = true;
        if (immediate) window.clearTimeout(timer);
        const revision = window.CappersNotifications?.revision();

        try {
            const url = new URL(summaryUrl, window.location.origin);
            if (cursorId !== null) {
                url.searchParams.set("after_id", String(cursorId));
            }

            const response = await fetch(url.toString(), {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            const contentType = response.headers.get("content-type") || "";
            if (!response.ok || !contentType.includes("application/json")) return;

            const data = await response.json();
            if (!data || !data.ok) return;

            // A summary started before a read must not bring an old dot back.
            if (revision === window.CappersNotifications?.revision()) {
                if (window.CappersNotifications) window.CappersNotifications.sync(data);
                else {
                    setBadge(data.unread_count);
                    setSectionBadges(data.section_badges || {});
                }
            }

            const serverLatestId = Number.parseInt(data.latest_id, 10) || 0;
            if (cursorId !== null && serverLatestId < cursorId) {
                cursorId = serverLatestId;
                persistCursor();
                return;
            }

            const notifications = Array.isArray(data.notifications) ? data.notifications : [];
            if (cursorId === null) {
                cursorId = Number.parseInt(data.cursor_id, 10) || 0;
                persistCursor();
                return;
            }

            if (notifications.length) {
                notifications.forEach(showToast);
                playSound();
                window.dispatchEvent(new CustomEvent("cappers:new-notifications", {
                    detail: { notifications },
                }));
            }

            const nextCursor = Number.parseInt(data.cursor_id, 10);
            if (Number.isFinite(nextCursor) && nextCursor >= cursorId) {
                cursorId = nextCursor;
                persistCursor();
            }
        } catch (error) {
            // Network hiccups should not affect the rest of the site.
        } finally {
            inFlight = false;
            scheduleNext();
        }
    };

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) poll({ immediate: true });
    });
    window.addEventListener("online", () => poll({ immediate: true }));
    window.addEventListener("cappers:notifications-changed", () => poll({ immediate: true }));

    poll({ immediate: true });
})();
