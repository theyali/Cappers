(() => {
    const page = document.querySelector(".profile-page");
    const input = document.getElementById("avatarUploadInput");
    const status = document.getElementById("avatarUploadStatus");

    if (!page) return;

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
