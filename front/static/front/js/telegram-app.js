(() => {
    // The Telegram Mini App shell: Telegram's colors, its system back button, haptics,
    // swipe-to-close, external links and Stars payments. Loaded only inside the Mini App.
    const SITE_COLOR = "#131313";

    const isSiteReferrer = () => {
        try {
            return Boolean(document.referrer) && new URL(document.referrer).origin === window.location.origin;
        } catch (error) {
            return false;
        }
    };

    const bindHaptics = (telegram) => {
        document.addEventListener("click", (event) => {
            const control = event.target.closest("a[href], button, [role='button'], .switch-control");
            if (!control || control.disabled) return;
            if (control.closest(".mobile-app-nav")) {
                telegram.HapticFeedback.selectionChanged();
            } else {
                telegram.HapticFeedback.impactOccurred("light");
            }
        });
    };

    const bindExternalLinks = (telegram) => {
        // Other sites open in Telegram's browser instead of replacing the Mini App.
        document.addEventListener("click", (event) => {
            const link = event.target.closest("a[href]");
            if (!link || event.defaultPrevented) return;
            const url = new URL(link.href, window.location.href);
            if (!/^https?:$/.test(url.protocol) || url.origin === window.location.origin) return;

            event.preventDefault();
            if (url.hostname === "t.me") {
                telegram.openTelegramLink(url.href);
            } else {
                telegram.openLink(url.href);
            }
        });
    };

    const bindStarsCheckout = (telegram) => {
        // Stars are paid in Telegram's own payment sheet, without leaving the app.
        document.addEventListener("click", async (event) => {
            const button = event.target.closest("button[name='provider'][value='telegram_stars']");
            if (!button || !button.form) return;
            event.preventDefault();
            if (button.disabled) return;

            button.disabled = true;
            const body = new FormData(button.form);
            body.set("provider", button.value);
            try {
                const response = await fetch(button.formAction, {
                    method: "POST",
                    body,
                    credentials: "same-origin",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.ok) {
                    throw new Error(data.message || "Не удалось создать оплату. Попробуйте позже.");
                }
                telegram.openInvoice(data.checkout_url, (status) => {
                    button.disabled = false;
                    if (status === "paid" || status === "pending") {
                        window.location.assign(data.return_url);
                    } else if (status === "failed") {
                        telegram.showAlert("Оплата не прошла. Попробуйте ещё раз.");
                    }
                });
            } catch (error) {
                button.disabled = false;
                telegram.showAlert(error.message);
            }
        });
    };

    const setUpBackButton = (telegram) => {
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

    const setUp = (telegram) => {
        telegram.ready();
        telegram.expand();
        bindExternalLinks(telegram);
        if (!telegram.isVersionAtLeast("6.1")) return;

        telegram.setHeaderColor(SITE_COLOR);
        telegram.setBackgroundColor(SITE_COLOR);
        if (telegram.isVersionAtLeast("7.10")) {
            telegram.setBottomBarColor(SITE_COLOR);
        }
        if (telegram.isVersionAtLeast("7.7")) {
            // Scrolling down must not close the app.
            telegram.disableVerticalSwipes();
        }
        bindHaptics(telegram);
        bindStarsCheckout(telegram);
        setUpBackButton(telegram);
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
