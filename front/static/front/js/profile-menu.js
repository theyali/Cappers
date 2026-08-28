(() => {
    const menus = Array.from(document.querySelectorAll("[data-profile-menu]"));
    if (!menus.length) return;

    const closeTimers = new WeakMap();

    const setOpen = (menu, isOpen) => {
        const toggle = menu.querySelector("[data-profile-menu-toggle]");
        window.clearTimeout(closeTimers.get(menu));
        menu.classList.toggle("is-open", isOpen);
        if (toggle) {
            toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        }
    };

    const scheduleClose = (menu) => {
        window.clearTimeout(closeTimers.get(menu));
        closeTimers.set(menu, window.setTimeout(() => setOpen(menu, false), 180));
    };

    menus.forEach((menu) => {
        const toggle = menu.querySelector("[data-profile-menu-toggle]");
        const dropdown = menu.querySelector("[data-profile-menu-dropdown]");
        if (!toggle || !dropdown) return;

        menu.addEventListener("pointerenter", () => setOpen(menu, true));
        menu.addEventListener("pointerleave", () => scheduleClose(menu));
        menu.addEventListener("focusin", () => setOpen(menu, true));
        menu.addEventListener("focusout", () => scheduleClose(menu));

        toggle.addEventListener("click", (event) => {
            event.stopPropagation();
            setOpen(menu, !menu.classList.contains("is-open"));
        });

        dropdown.addEventListener("click", (event) => {
            event.stopPropagation();
        });
    });

    document.addEventListener("click", () => {
        menus.forEach((menu) => setOpen(menu, false));
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        menus.forEach((menu) => setOpen(menu, false));
        const activeMenu = document.activeElement?.closest?.("[data-profile-menu]");
        activeMenu?.querySelector("[data-profile-menu-toggle]")?.focus();
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

    const loadNotificationStyles = () => {
        if (document.querySelector("link[data-notification-header-styles]")) return;
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "/static/notifications/css/header.css";
        link.dataset.notificationHeaderStyles = "true";
        document.head.appendChild(link);
    };

    const ensureReaderAvatarInput = () => {
        const page = document.querySelector(".profile-page");
        const readerHero = page?.querySelector(".profile-hero.is-reader");
        const wrap = readerHero?.querySelector(".profile-avatar-wrap");
        if (!page || !wrap || document.getElementById("avatarUploadInput")) return;

        const label = document.createElement("label");
        label.className = "avatar-upload-button";
        label.htmlFor = "avatarUploadInput";
        label.title = "Изменить аватар";
        label.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h3l1.4-2h7.2L17 7h3v12H4z"></path><circle cx="12" cy="13" r="3.2"></circle></svg>';

        const input = document.createElement("input");
        input.id = "avatarUploadInput";
        input.className = "avatar-upload-input";
        input.type = "file";
        input.accept = "image/jpeg,image/png,image/webp";

        wrap.append(label, input);
    };

    const replaceProfileAvatar = (url) => {
        if (!url) return;
        const avatar = document.getElementById("profileAvatar");
        if (!avatar) return;
        let image = document.getElementById("profileAvatarImage");
        const fallback = document.getElementById("profileAvatarFallback");
        if (!image) {
            image = document.createElement("img");
            image.id = "profileAvatarImage";
            image.alt = "Аватар профиля";
            fallback?.remove();
            avatar.appendChild(image);
        }
        image.src = url;
    };

    const replaceHeaderAvatar = (url) => {
        if (!url) return;
        document.querySelectorAll(".nav-profile img, .nav-profile-dropdown-avatar img").forEach((image) => {
            image.src = url;
            image.classList.add("nav-profile-avatar-image");
        });
    };

    const ensureNotificationNavigation = () => {
        const menu = menus[0];
        const actions = menu.closest(".site-nav-actions");
        const dropdown = menu.querySelector("[data-profile-menu-dropdown]");
        if (!actions || !dropdown) return null;

        let bell = actions.querySelector(".nav-notification-link");
        if (!bell) {
            bell = document.createElement("a");
            bell.className = "nav-notification-link";
            bell.href = "/notifications/";
            bell.title = "Уведомления";
            bell.setAttribute("aria-label", "Уведомления");
            bell.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"></path><path d="M10 21h4"></path></svg><span class="nav-notification-badge is-empty" data-notification-badge></span>';
            actions.insertBefore(bell, menu);
        }

        if (!dropdown.querySelector('[href="/notifications/"]')) {
            const link = document.createElement("a");
            link.href = "/notifications/";
            link.innerHTML = '<span class="nav-profile-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"></path><path d="M10 21h4"></path></svg></span><span>Уведомления</span>';
            const head = dropdown.querySelector(".nav-profile-dropdown-head");
            if (head?.nextSibling) {
                dropdown.insertBefore(link, head.nextSibling);
            } else {
                dropdown.appendChild(link);
            }
        }
        return bell;
    };

    const setBadge = (bell, unreadCount) => {
        const badge = bell?.querySelector("[data-notification-badge]");
        if (!badge) return;
        const count = Number(unreadCount) || 0;
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.classList.toggle("is-empty", count <= 0);
    };

    const initMatchWatch = () => {
        const head = document.querySelector(".match-detail-card .match-detail-head");
        if (!head || head.querySelector(".match-watch-button")) return;
        if (head.querySelector(".match-status-finished")) return;

        const bets = document.querySelector("[data-match-bets][data-match-id]");
        let url = "";
        if (bets?.dataset.matchId) {
            url = `/notifications/matches/${bets.dataset.matchId}/watch/`;
        } else {
            const pathMatch = window.location.pathname.match(/^\/games\/([^/]+)\/?$/);
            const matchSlug = pathMatch?.[1] ? decodeURIComponent(pathMatch[1]) : "";
            if (matchSlug) {
                url = `/notifications/matches/slug/${encodeURIComponent(matchSlug)}/watch/`;
            }
        }
        if (!url) return;

        const button = document.createElement("button");
        button.type = "button";
        button.className = "match-watch-button";
        button.textContent = "Следить за матчем";
        head.appendChild(button);

        const setWatching = (watching) => {
            button.classList.toggle("is-watching", Boolean(watching));
            button.textContent = watching ? "Матч отслеживается" : "Следить за матчем";
        };

        fetch(url, { credentials: "same-origin", cache: "no-store" })
            .then((response) => response.ok ? response.json() : null)
            .then((payload) => {
                if (payload?.ok) setWatching(payload.watching);
            })
            .catch(() => {});

        button.addEventListener("click", async () => {
            if (button.disabled) return;
            button.disabled = true;
            try {
                const response = await fetch(url, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                const payload = await response.json();
                if (!response.ok || !payload.ok) {
                    throw new Error(payload?.error || "Не удалось обновить отслеживание");
                }
                setWatching(payload.watching);
            } catch (error) {
                button.textContent = error?.message || "Не удалось обновить";
                window.setTimeout(() => setWatching(button.classList.contains("is-watching")), 1700);
            } finally {
                button.disabled = false;
            }
        });
    };

    const loadRealtimeNotifications = (bell) => {
        if (!bell) return;
        bell.dataset.notificationNav = "";
        bell.dataset.summaryUrl = "/notifications/summary/";
        bell.dataset.soundUrl = "/static/front/sounds/notification.wav";
        bell.dataset.userId = menuUserKey();

        if (!document.querySelector("link[data-notification-realtime-styles]")) {
            const style = document.createElement("link");
            style.rel = "stylesheet";
            style.href = "/static/notifications/css/realtime.css";
            style.dataset.notificationRealtimeStyles = "true";
            document.head.appendChild(style);
        }

        if (!document.querySelector("script[data-notification-realtime-script]")) {
            const script = document.createElement("script");
            script.src = "/static/notifications/js/realtime.js";
            script.dataset.notificationRealtimeScript = "true";
            document.body.appendChild(script);
        }
    };

    const menuUserKey = () => {
        const username = menus[0]
            ?.querySelector(".nav-profile-dropdown-head span")
            ?.textContent
            ?.trim();
        return username || "authenticated-user";
    };

    loadNotificationStyles();
    ensureReaderAvatarInput();
    const bell = ensureNotificationNavigation();
    initMatchWatch();
    loadRealtimeNotifications(bell);

    fetch("/notifications/summary/", { credentials: "same-origin", cache: "no-store" })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => {
            if (!payload?.ok) return;
            setBadge(bell, payload.unread_count);
            replaceHeaderAvatar(payload.avatar_url);
            replaceProfileAvatar(payload.avatar_url);
        })
        .catch(() => {});
})();

(() => {
    if (!document.querySelector(".profile-page")) return;
    if (document.querySelector("script[data-profile-referrals-script]")) return;
    const script = document.createElement("script");
    script.src = "/static/front/js/profile-referrals.js";
    script.dataset.profileReferralsScript = "true";
    document.body.appendChild(script);
})();

(() => {
    if (!document.querySelector(".profile-page")) return;
    if (document.querySelector("script[data-profile-demand-script]")) return;
    const script = document.createElement("script");
    script.src = "/static/front/js/profile-demand.js";
    script.dataset.profileDemandScript = "true";
    document.body.appendChild(script);
})();

(() => {
    if (!document.querySelector("[data-match-bets][data-match-id]")) return;
    if (document.querySelector("script[data-match-demand-script]")) return;
    const script = document.createElement("script");
    script.src = "/static/front/js/match-demand.js";
    script.dataset.matchDemandScript = "true";
    document.body.appendChild(script);
})();
