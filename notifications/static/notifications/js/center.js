(() => {
    const page = document.querySelector("[data-notifications-page]");
    if (!page) return;

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

    const unreadCounter = page.querySelector("[data-unread-count]");
    const setUnread = (value) => {
        if (!unreadCounter) return;
        unreadCounter.textContent = String(Math.max(0, value));
    };

    const notifyGlobalStateChanged = () => {
        window.dispatchEvent(new Event("cappers:notifications-changed"));
    };

    page.querySelectorAll("[data-notification-link]").forEach((link) => {
        link.addEventListener("click", async (event) => {
            if (!link.classList.contains("is-unread")) return;
            const href = link.getAttribute("href");
            const readUrl = link.dataset.readUrl;
            if (!readUrl) return;

            event.preventDefault();
            window.CappersSkeleton?.loading(link);
            try {
                const response = await fetch(readUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                if (response.ok) {
                    link.classList.remove("is-unread");
                    link.querySelector(".notification-unread-dot")?.remove();
                    const current = Number.parseInt(unreadCounter?.textContent || "0", 10) || 0;
                    setUnread(current - 1);
                    notifyGlobalStateChanged();
                }
            } finally {
                window.CappersSkeleton?.ready(link);
                if (href && href !== "#") window.location.href = href;
            }
        });
    });

    const markAllForm = page.querySelector("[data-mark-all-form]");
    if (markAllForm) {
        markAllForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const button = markAllForm.querySelector("button");
            const list = page.querySelector(".notifications-list");
            if (button) button.disabled = true;
            window.CappersSkeleton?.loading(list);
            try {
                const response = await fetch(markAllForm.action, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                if (!response.ok) throw new Error("Не удалось обновить уведомления.");
                page.querySelectorAll(".notification-row.is-unread").forEach((row) => {
                    row.classList.remove("is-unread");
                    row.querySelector(".notification-unread-dot")?.remove();
                });
                setUnread(0);
                markAllForm.remove();
                notifyGlobalStateChanged();
            } catch (error) {
                if (button) button.disabled = false;
            } finally {
                window.CappersSkeleton?.ready(list);
            }
        });
    }

    const settingsForm = page.querySelector("[data-notification-settings-form]");
    if (settingsForm) {
        settingsForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const block = settingsForm.closest("[data-notification-settings-block]");
            const button = settingsForm.querySelector("[data-settings-save]");
            const originalText = button?.textContent || "Сохранить настройки";

            if (button) button.disabled = true;
            window.CappersSkeleton?.loading(block);
            try {
                const response = await fetch(settingsForm.action, {
                    method: "POST",
                    credentials: "same-origin",
                    body: new FormData(settingsForm),
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || payload.ok === false) {
                    throw new Error(payload.error || "Не удалось сохранить настройки.");
                }
                if (button) button.textContent = payload.message || "Сохранено";
            } catch (error) {
                if (button) button.textContent = "Не удалось сохранить";
            } finally {
                if (button) {
                    button.disabled = false;
                    window.setTimeout(() => {
                        button.textContent = originalText;
                    }, 1600);
                }
                window.CappersSkeleton?.ready(block);
            }
        });
    }
})();
