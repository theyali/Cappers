(() => {
    const page = document.querySelector(".profile-page");
    const input = document.getElementById("avatarUploadInput");
    const status = document.getElementById("profileAvatarStatus");

    if (!page) return;

    const loadJQuery = () => {
        if (window.jQuery) return Promise.resolve(window.jQuery);

        return new Promise((resolve, reject) => {
            let script = document.querySelector("script[data-profile-jquery]");
            if (!script) {
                script = document.createElement("script");
                script.src = "https://code.jquery.com/jquery-3.7.1.min.js";
                script.dataset.profileJquery = "true";
                script.async = true;
                document.head.appendChild(script);
            }

            const onLoad = () => {
                if (window.jQuery) {
                    resolve(window.jQuery);
                } else {
                    reject(new Error("jQuery не загрузился."));
                }
            };
            const onError = () => reject(new Error("Не удалось загрузить jQuery."));

            if (window.jQuery) {
                resolve(window.jQuery);
                return;
            }

            script.addEventListener("load", onLoad, { once: true });
            script.addEventListener("error", onError, { once: true });
        });
    };

    const initCouponInline = ($) => {
        const duration = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 220;

        $(".profile-coupons-list:not([data-profile-coupon-inline='false']) > .profile-coupon-row[href]").each(function (index) {
            const $source = $(this);
            if ($source.data("coupon-inline-ready")) return;

            const detailUrl = $source.attr("href");
            if (!detailUrl) return;

            const idMatch = detailUrl.match(/\/coupons\/(\d+)\//);
            const inlineId = `profile-coupon-inline-${idMatch ? idMatch[1] : index}`;
            const $row = $("<div>", {
                class: $source.attr("class") || "profile-coupon-row",
            });
            $row.data("coupon-inline-ready", true);
            $row.append($source.contents());

            const $actions = $("<div>", { class: "profile-coupon-actions" });
            const $view = $("<a>", {
                class: "profile-coupon-view",
                href: detailUrl,
                text: "Посмотреть",
            });
            const $expand = $("<button>", {
                class: "profile-coupon-expand",
                type: "button",
                text: "Раскрыть",
                "aria-expanded": "false",
                "aria-controls": inlineId,
            });
            $actions.append($view, $expand);

            const $legacyOpen = $row.find(".profile-coupon-open").first();
            if ($legacyOpen.length) {
                $legacyOpen.replaceWith($actions);
            } else {
                $row.append($actions);
            }

            const $inline = $("<div>", {
                id: inlineId,
                class: "profile-coupon-inline",
                "aria-hidden": "true",
            });
            const $card = $("<article>", { class: "profile-coupon-card" });

            $source.replaceWith($card);
            $card.append($row, $inline);

            let loaded = false;
            let loading = false;

            const closeInline = () => {
                $inline.stop(true, true).slideUp(duration, () => {
                    $inline.attr("aria-hidden", "true");
                });
                $expand.attr("aria-expanded", "false").text("Раскрыть");
            };

            const openInline = () => {
                $inline.attr("aria-hidden", "false").stop(true, true).slideDown(duration);
                $expand.attr("aria-expanded", "true").text("Скрыть");
            };

            const loadCoupon = () => {
                if (loading) return;
                loading = true;
                $expand.prop("disabled", true).text("Загрузка…");
                $inline.removeClass("is-error");

                $.ajax({
                    url: detailUrl,
                    method: "GET",
                    dataType: "html",
                    cache: false,
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                })
                    .done((html) => {
                        const parsed = $.parseHTML(html, document, false) || [];
                        const $response = $("<div>").append(parsed);
                        const $panel = $response.find(".coupon-detail-panel").first();

                        if (!$panel.length) {
                            throw new Error("Сервер не вернул матчи купона.");
                        }

                        $inline.empty().append($panel);
                        loaded = true;
                        openInline();
                    })
                    .fail(() => {
                        $inline
                            .addClass("is-error")
                            .html('<div class="profile-coupon-inline-error">Не удалось загрузить матчи купона. Нажмите «Раскрыть» ещё раз.</div>')
                            .attr("aria-hidden", "false")
                            .stop(true, true)
                            .slideDown(duration);
                        $expand.attr("aria-expanded", "true").text("Повторить");
                    })
                    .always(() => {
                        loading = false;
                        $expand.prop("disabled", false);
                        if (loaded && $inline.is(":visible")) {
                            $expand.text("Скрыть");
                        } else if (!loaded && !$inline.is(":visible")) {
                            $expand.text("Раскрыть");
                        }
                    });
            };

            $expand.on("click", () => {
                if (loading) return;

                if (loaded) {
                    if ($inline.is(":visible")) {
                        closeInline();
                    } else {
                        openInline();
                    }
                    return;
                }

                if ($inline.is(":visible") && $inline.hasClass("is-error")) {
                    $inline.stop(true, true).hide().attr("aria-hidden", "true");
                }
                loadCoupon();
            });
        });
    };

    if (document.querySelector(".profile-coupons-list:not([data-profile-coupon-inline='false']) > .profile-coupon-row[href]")) {
        loadJQuery()
            .then(initCouponInline)
            .catch((error) => console.error(error));
    }

    const tabLinks = Array.from(document.querySelectorAll("[data-profile-tab-link]"));
    const tabPanels = Array.from(document.querySelectorAll("[data-profile-tab-panel]"));

    const activateTab = (tab) => {
        tabPanels.forEach((panel) => {
            panel.classList.toggle("is-active", panel.dataset.profileTabPanel === tab);
        });

        tabLinks.forEach((link) => {
            const target = new URL(link.href, window.location.href).searchParams.get("tab") || "profile";
            link.classList.toggle("is-active", target === tab);
        });
    };

    tabLinks.forEach((link) => {
        link.addEventListener("click", (event) => {
            const url = new URL(link.href, window.location.href);
            const tab = url.searchParams.get("tab") || "profile";
            if (!tabPanels.some((panel) => panel.dataset.profileTabPanel === tab)) return;

            event.preventDefault();
            window.history.pushState({}, "", url);
            activateTab(tab);
        });
    });

    window.addEventListener("popstate", () => {
        const tab = new URL(window.location.href).searchParams.get("tab") || "profile";
        activateTab(tab);
    });

    document.querySelectorAll("[data-profile-list-search]").forEach((searchInput) => {
        searchInput.addEventListener("input", () => {
            const listName = searchInput.dataset.profileListSearch;
            const list = document.querySelector(`[data-profile-list="${listName}"]`);
            if (!list) return;

            const query = searchInput.value.trim().toLowerCase();
            list.querySelectorAll("[data-profile-username]").forEach((row) => {
                row.classList.toggle(
                    "is-hidden",
                    query !== "" && !row.dataset.profileUsername.includes(query),
                );
            });
        });
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

    document.querySelectorAll("[data-follow-url]").forEach((button) => {
        button.addEventListener("click", async () => {
            if (button.disabled) return;

            const originalText = button.textContent;
            button.disabled = true;
            button.textContent = "Подписываем...";

            try {
                const response = await fetch(button.dataset.followUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                const payload = await response.json();
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.error || "Не удалось подписаться.");
                }

                button.textContent = "Вы подписаны";
                button.classList.add("is-muted");
                button.removeAttribute("data-follow-url");
            } catch (error) {
                button.textContent = error.message || originalText;
                window.setTimeout(() => {
                    button.textContent = originalText;
                    button.disabled = false;
                }, 1800);
            }
        });
    });

    if (!input || !status) return;

    const uploadUrl = page.dataset.avatarUploadUrl;

    const showStatus = (message, isError = false) => {
        status.textContent = message;
        status.classList.toggle("is-error", isError);
    };

    const replaceAvatar = (url) => {
        const avatar = document.getElementById("profileAvatar");
        if (!avatar) return;

        let image = document.getElementById("profileAvatarImage");
        const fallback = document.getElementById("profileAvatarFallback");

        if (!image) {
            image = document.createElement("img");
            image.id = "profileAvatarImage";
            image.alt = "Аватар профиля";
            if (fallback) fallback.remove();
            avatar.appendChild(image);
        }

        image.src = `${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`;
    };

    input.addEventListener("change", async () => {
        const file = input.files && input.files[0];
        if (!file) return;

        const allowed = ["image/jpeg", "image/png", "image/webp"];
        if (!allowed.includes(file.type)) {
            showStatus("Разрешены только JPG, PNG и WebP.", true);
            input.value = "";
            return;
        }

        if (file.size > 5 * 1024 * 1024) {
            showStatus("Файл больше 5 МБ.", true);
            input.value = "";
            return;
        }

        const data = new FormData();
        data.append("avatar", file);
        showStatus("Загружаем аватар…");
        input.disabled = true;

        try {
            const response = await fetch(uploadUrl, {
                method: "POST",
                body: data,
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest",
                },
            });

            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || "Не удалось загрузить аватар.");
            }

            replaceAvatar(payload.avatar_url);
            showStatus(payload.message || "Аватар обновлён.");
        } catch (error) {
            showStatus(error.message || "Ошибка загрузки.", true);
        } finally {
            input.disabled = false;
            input.value = "";
        }
    });
})();

(() => {
    const page = document.querySelector(".profile-page");
    if (!page) return;

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const wireRow = (row, url) => {
        if (!row || !url) return;
        row.classList.add("is-profile-link");
        row.tabIndex = 0;
        row.dataset.profileUrl = url;
        row.addEventListener("click", (event) => {
            if (event.target.closest("a, button, input, label")) return;
            window.location.href = url;
        });
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter") window.location.href = url;
        });
    };

    const followersList = page.querySelector('[data-profile-list="followers"]');
    if (followersList) {
        followersList.querySelectorAll("[data-profile-username]").forEach((row) => {
            const username = row.dataset.profileUsername || "";
            if (!username) return;
            const url = `/cabinet/users/${encodeURIComponent(username)}/`;
            wireRow(row, url);
            const disabled = row.querySelector(".profile-row-action[disabled]");
            if (disabled) {
                const link = document.createElement("a");
                link.className = "profile-user-open";
                link.href = url;
                link.textContent = "Открыть профиль";
                disabled.replaceWith(link);
            }
        });
    }

    const followingList = page.querySelector('[data-profile-list="following"]');
    if (!followingList) return;

    fetch("/cabinet/profile/following/summary/", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
    })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => {
            if (!payload?.ok) return;
            const byUsername = new Map((payload.items || []).map((item) => [String(item.username).toLowerCase(), item]));
            followingList.querySelectorAll("[data-profile-username]").forEach((row) => {
                const item = byUsername.get((row.dataset.profileUsername || "").toLowerCase());
                if (!item) return;
                const avatar = item.avatar_url
                    ? `<div class="profile-user-avatar"><img src="${escapeHtml(item.avatar_url)}" alt=""></div>`
                    : `<div class="profile-user-avatar">${escapeHtml(item.display_name || item.username).slice(0, 1).toUpperCase()}</div>`;
                const verified = item.is_verified ? '<span class="profile-user-verified">Проверен</span>' : "";
                row.innerHTML = `
                    ${avatar}
                    <div class="profile-user-copy">
                        <strong>${escapeHtml(item.display_name || item.username)}</strong>
                        <span>@${escapeHtml(item.username)}${item.specialization ? ` · ${escapeHtml(item.specialization)}` : ""}</span>
                        <div class="profile-user-meta">
                            <span>${escapeHtml(item.predictions_count)} прогнозов</span>
                            <span>${escapeHtml(item.followers_count)} подписчиков</span>
                            ${verified}
                        </div>
                    </div>
                    <a class="profile-user-open" href="${escapeHtml(item.url)}">Открыть профиль</a>`;
                wireRow(row, item.url);
            });
        })
        .catch(() => {});
})();

(() => {
    const page = document.querySelector(".profile-page");
    const tabs = page?.querySelector(".profile-tabs");
    if (!page || !tabs || page.querySelector('[data-profile-tab-panel="achievements"]')) return;

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const currentTab = () => new URL(window.location.href).searchParams.get("tab") || "profile";

    const activate = (panel, tab) => {
        page.querySelectorAll("[data-profile-tab-panel]").forEach((item) => item.classList.remove("is-active"));
        tabs.querySelectorAll("a").forEach((item) => item.classList.remove("is-active"));
        panel.classList.add("is-active");
        tab.classList.add("is-active");
    };

    const deactivate = (panel, tab) => {
        panel.classList.remove("is-active");
        tab.classList.remove("is-active");
    };

    fetch("/cabinet/profile/achievements/", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
    })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => {
            if (!payload?.ok || payload.is_analyst) return;

            const tab = document.createElement("a");
            tab.href = `${window.location.pathname}?tab=achievements`;
            tab.textContent = "Достижения";
            tab.dataset.readerAchievementTab = "";
            tabs.insertBefore(tab, tabs.querySelector('a[href*="tab=following"]') || null);

            const cards = (payload.items || []).map((item) => `
                <article class="profile-achievement-card${item.unlocked ? " is-unlocked" : " is-locked"}" data-achievement="${escapeHtml(item.key)}">
                    <div class="profile-achievement-topline">
                        <span class="profile-achievement-icon"><img src="/static/${escapeHtml(item.icon)}" alt=""></span>
                        <span class="profile-achievement-state${item.unlocked ? " is-unlocked" : ""}">${item.unlocked ? "Получено" : `${escapeHtml(item.progress)}%`}</span>
                    </div>
                    <span class="profile-achievement-category">${escapeHtml(item.category)}</span>
                    <h3>${escapeHtml(item.label)}</h3>
                    <p>${escapeHtml(item.description)}</p>
                    <div class="profile-achievement-progress"><i style="width: ${Number(item.progress) || 0}%"></i></div>
                    <div class="profile-achievement-meta"><span>Сейчас: ${escapeHtml(item.current_label)}</span><strong>Цель: ${escapeHtml(item.target_label)}</strong></div>
                </article>`).join("");

            const next = payload.next_achievement
                ? `<article class="profile-next-achievement">
                    <span class="profile-next-achievement-icon"><img src="/static/${escapeHtml(payload.next_achievement.icon)}" alt=""></span>
                    <div><span>Ближайшая ачивка</span><strong>${escapeHtml(payload.next_achievement.label)}</strong><small>${escapeHtml(payload.next_achievement.description)}</small></div>
                    <div class="profile-next-achievement-progress"><strong>${escapeHtml(payload.next_achievement.progress)}%</strong><span>${escapeHtml(payload.next_achievement.current_label)} / ${escapeHtml(payload.next_achievement.target_label)}</span></div>
                </article>`
                : '<article class="profile-next-achievement is-complete"><div><span>Коллекция завершена</span><strong>Все достижения получены</strong></div></article>';

            const panel = document.createElement("section");
            panel.className = "profile-tab-panel";
            panel.dataset.profileTabPanel = "achievements";
            panel.id = "profile-tab-achievements";
            panel.innerHTML = `
                <div class="profile-achievements-shell">
                    <div class="profile-achievements-head">
                        <div><p class="eyebrow">Ваш прогресс</p><h2>Достижения</h2><p>Ачивки за лайки и сохранённые прогнозы.</p></div>
                        <div class="profile-achievements-total"><strong>${escapeHtml(payload.unlocked_count)}/${escapeHtml(payload.total_count)}</strong><span>получено</span></div>
                    </div>
                    <div class="profile-achievements-overall"><div><span>Общий прогресс</span><strong>${escapeHtml(payload.completion_percent)}%</strong></div><div class="profile-achievements-track"><i style="width: ${Number(payload.completion_percent) || 0}%"></i></div></div>
                    ${next}
                    <div class="profile-achievements-grid">${cards}</div>
                </div>`;

            const followingPanel = page.querySelector('[data-profile-tab-panel="following"]');
            page.insertBefore(panel, followingPanel || null);

            tab.addEventListener("click", (event) => {
                event.preventDefault();
                const url = new URL(tab.href, window.location.href);
                window.history.pushState({}, "", url);
                activate(panel, tab);
            });

            tabs.querySelectorAll("a:not([data-reader-achievement-tab])").forEach((link) => {
                link.addEventListener("click", () => deactivate(panel, tab));
            });

            window.addEventListener("popstate", () => {
                if (currentTab() === "achievements") activate(panel, tab);
                else deactivate(panel, tab);
            });

            if (currentTab() === "achievements") activate(panel, tab);
        })
        .catch(() => {});
})();
