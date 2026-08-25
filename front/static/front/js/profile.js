(() => {
    const page = document.querySelector(".profile-page");
    const input = document.getElementById("avatarUploadInput");
    const status = document.getElementById("avatarUploadStatus");

    if (!page || !input || !status) return;

    const uploadUrl = page.dataset.avatarUploadUrl;

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
