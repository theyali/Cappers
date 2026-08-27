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

    page.querySelectorAll("[data-notification-link]").forEach((link) => {
        link.addEventListener("click", async (event) => {
            if (!link.classList.contains("is-unread")) return;
            const href = link.getAttribute("href");
            const readUrl = link.dataset.readUrl;
            if (!readUrl) return;

            event.preventDefault();
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
                }
            } finally {
                if (href && href !== "#") window.location.href = href;
            }
        });
    });

    const markAllForm = page.querySelector("[data-mark-all-form]");
    if (markAllForm) {
        markAllForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const button = markAllForm.querySelector("button");
            if (button) button.disabled = true;
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
            } catch (error) {
                if (button) button.disabled = false;
            }
        });
    }
})();
