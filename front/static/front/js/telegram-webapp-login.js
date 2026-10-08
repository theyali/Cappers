(() => {
    const entry = document.querySelector("[data-telegram-entry]");
    if (!entry) return;

    const status = document.getElementById("telegram-entry-status");
    const statusText = document.getElementById("telegram-entry-text");
    const csrfToken = entry.querySelector("[name=csrfmiddlewaretoken]").value;

    const fail = (message) => {
        status.classList.add("is-error");
        statusText.textContent = message;
    };

    // Telegram opens the page with the signed login data after "#", as tgWebAppData.
    const initData = new URLSearchParams(window.location.hash.slice(1)).get("tgWebAppData") || "";
    if (!initData) {
        fail(
            window.TelegramWebviewProxy
                ? "Telegram не передал данные входа. Вернитесь в бот и нажмите «Открыть сайт»."
                : "Откройте сайт через кнопку в Telegram-боте."
        );
        return;
    }

    fetch(entry.dataset.endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-CSRFToken": csrfToken,
        },
        body: new URLSearchParams({ init_data: initData, next: entry.dataset.next || "" }).toString(),
    })
        .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok) {
                throw new Error(data.message || "Не удалось выполнить вход.");
            }
            return data;
        })
        .then((data) => {
            statusText.textContent = "Готово. Открываем сайт…";
            window.location.replace(data.redirect || "/cabinet/");
        })
        .catch((error) => {
            fail(error.message || "Не удалось выполнить вход через Telegram.");
        });
})();
