(() => {
    const page = document.querySelector(".profile-page");
    const input = document.getElementById("avatarUploadInput");
    const status = document.getElementById("profileAvatarStatus");

    if (!page) return;

    const loadCouponInlineStyles = () => {
        if (document.querySelector("link[data-profile-coupon-inline-styles]")) return;

        const profileScript = Array.from(document.scripts).find((script) =>
            script.src.includes("/front/js/profile.js"),
        );
        if (!profileScript || !profileScript.src) return;

        const href = profileScript.src.replace(
            /\/front\/js\/profile\.js(?:\?.*)?$/,
            "/front/css/profile-coupon-inline.css",
        );
        if (!href || href === profileScript.src) return;

        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = href;
        link.dataset.profileCouponInlineStyles = "true";
        document.head.appendChild(link);
    };

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

        $(".profile-coupons-list > .profile-coupon-row[href]").each(function (index) {
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

    if (document.querySelector(".profile-coupons-list > .profile-coupon-row[href]")) {
        loadCouponInlineStyles();
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
