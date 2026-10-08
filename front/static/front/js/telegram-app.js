(() => {
    // The Telegram Mini App shell: Telegram's colors and its system back button.
    // Loaded only when the page is open inside the Mini App.
    const SITE_COLOR = "#131313";

    const isSiteReferrer = () => {
        try {
            return Boolean(document.referrer) && new URL(document.referrer).origin === window.location.origin;
        } catch (error) {
            return false;
        }
    };

    const setUp = (telegram) => {
        telegram.ready();
        telegram.expand();
        if (!telegram.isVersionAtLeast("6.1")) return;

        telegram.setHeaderColor(SITE_COLOR);
        telegram.setBackgroundColor(SITE_COLOR);
        if (telegram.isVersionAtLeast("7.10")) {
            telegram.setBottomBarColor(SITE_COLOR);
        }

        // Bottom menu sections are the top level: Telegram shows "Close" there and "Back" elsewhere.
        const rootPaths = new Set(["/"]);
        document.querySelectorAll(".mobile-app-nav a[href]").forEach((link) => {
            rootPaths.add(new URL(link.href, window.location.href).pathname);
        });
        if (rootPaths.has(window.location.pathname)) {
            telegram.BackButton.hide();
            return;
        }

        telegram.BackButton.onClick(() => {
            if (isSiteReferrer() && window.history.length > 1) {
                window.history.back();
            } else {
                window.location.assign("/");
            }
        });
        telegram.BackButton.show();
    };

    const start = () => {
        const telegram = window.Telegram && window.Telegram.WebApp;
        if (telegram) setUp(telegram);
    };

    if (window.Telegram && window.Telegram.WebApp) {
        start();
    } else {
        document.getElementById("telegram-web-app-sdk")?.addEventListener("load", start, { once: true });
    }
})();
