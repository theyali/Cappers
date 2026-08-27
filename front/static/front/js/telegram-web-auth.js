(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("tg_webapp") !== "1") return;

    let authenticating = false;

    const cleanUrl = () => {
        const url = new URL(window.location.href);
        url.searchParams.delete("tg_webapp");
        return `${url.pathname}${url.search}${url.hash}`;
    };

    const authenticate = async () => {
        if (authenticating) return;
        const webApp = window.Telegram?.WebApp;
        const initData = String(webApp?.initData || "").trim();
        if (!initData) return;

        authenticating = true;
        try {
            webApp.ready?.();
            const body = new URLSearchParams({ init_data: initData });
            const response = await fetch("/notifications/telegram/web-auth/", {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    Accept: "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: body.toString(),
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok || !payload?.ok) return;

            window.location.replace(cleanUrl());
        } catch (error) {
            // If Telegram auth is unavailable, leave the normal site login flow untouched.
        } finally {
            authenticating = false;
        }
    };

    if (window.Telegram?.WebApp) {
        authenticate();
        return;
    }

    const existing = document.querySelector('script[data-telegram-webapp-sdk]');
    if (existing) {
        existing.addEventListener("load", authenticate, { once: true });
        return;
    }

    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-web-app.js";
    script.async = true;
    script.dataset.telegramWebappSdk = "true";
    script.addEventListener("load", authenticate, { once: true });
    document.head.appendChild(script);
})();
