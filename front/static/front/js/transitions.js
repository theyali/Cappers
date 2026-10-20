(() => {
    const overlay = document.querySelector(".logo-transition");
    if (!overlay) return;

    let isLeaving = false;
    let resetTimer = 0;

    const hideTransition = () => {
        isLeaving = false;
        window.clearTimeout(resetTimer);
        overlay.classList.remove("is-active");
    };

    const showTransition = () => {
        if (isLeaving) return;
        isLeaving = true;
        overlay.classList.add("is-active");
        resetTimer = window.setTimeout(hideTransition, 3000);
    };

    const transitionDuration = 420;
    // In the Telegram Mini App pages change at once and View Transitions animate them.
    const isTelegramApp = document.body.classList.contains("is-telegram-app");
    const couponDetailPath = /^\/predictions\/\d+\/?$/;
    const matchDetailPath = /^\/games\/[^/]+\/?$/;

    const isModifiedClick = (event) => (
        event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0
    );

    const rememberCouponMatchRoundTrip = (sourceUrl, targetUrl) => {
        if (!couponDetailPath.test(sourceUrl.pathname) || !matchDetailPath.test(targetUrl.pathname)) return;
        try {
            sessionStorage.setItem(`cappers:coupon-match-return:${targetUrl.pathname}`, JSON.stringify({
                couponHref: sourceUrl.href,
                savedAt: Date.now(),
            }));
        } catch (error) {
            // Navigation still works normally when sessionStorage is unavailable.
        }
    };

    document.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        if (!link || event.defaultPrevented || isModifiedClick(event)) return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download")) return;
        if (link.hasAttribute("data-expert-public-modal-open")) return;
        if (link.hasAttribute("data-profile-tab-link")) return;
        if (link.hasAttribute("data-prediction-ajax-link")) return;
        if (link.hasAttribute("data-copy-nav") || link.hasAttribute("data-copy-more")) return;
        if (link.closest(".matches-table-filter-sidebar, .matches-head, .matches-sport-tabs, .feed-sport-tabs, .matches-tabs, .matches-date-filter, .cappers-period-filter, .home-best-experts-periods")) return;
        if (link.hasAttribute("data-mobile-coupon-toggle")) {
            event.preventDefault();
            return;
        }

        const url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin) return;
        if (url.pathname === window.location.pathname && url.search === window.location.search) return;
        if (url.hash && url.pathname === window.location.pathname && url.search === window.location.search) return;

        rememberCouponMatchRoundTrip(new URL(window.location.href), url);
        if (isTelegramApp) return;
        event.preventDefault();
        showTransition();
        window.setTimeout(() => {
            window.location.href = url.href;
        }, transitionDuration);
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (event.defaultPrevented || isTelegramApp) return;
        if (form.matches("[data-no-transition]")) return;
        if (form.dataset.transitionSubmitted === "true") return;

        event.preventDefault();
        form.dataset.transitionSubmitted = "true";
        showTransition();
        window.setTimeout(() => {
            form.submit();
        }, transitionDuration);
    });

    window.addEventListener("pageshow", hideTransition);
    window.addEventListener("load", hideTransition);
    window.addEventListener("focus", hideTransition);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) hideTransition();
    });
})();

(() => {
    const banner = document.querySelector("[data-cookie-banner]");
    const dialog = document.querySelector("[data-cookie-preferences]");
    if (!banner || !dialog) return;
    const COOKIE_NAME = "capperhub_cookie_consent";
    const STORAGE_KEY = "capperhub.cookieConsent";
    const PREFERENCES_KEY = "capperhub.cookiePreferences";
    const PREFERENCES_COOKIE = "capperhub_cookie_preferences";
    const categories = ["analytics", "functional", "advertising"];
    const controls = Array.from(dialog.querySelectorAll("[data-cookie-category]"));
    const readCookie = (name) => document.cookie.split(";").map((item) => item.trim())
        .find((item) => item.startsWith(name + "="))?.slice(name.length + 1) || "";
    const readStorage = (key) => {
        for (const storage of [() => localStorage, () => sessionStorage]) {
            try { const value = storage().getItem(key); if (value) return value; } catch (_) { /* Try the next available storage. */ }
        }
        return "";
    };
    const choice = readCookie(COOKIE_NAME) || readStorage(STORAGE_KEY);
    let preferences = Object.fromEntries(categories.map((key) => [key, choice === "accepted"]));
    try {
        const stored = JSON.parse(decodeURIComponent(readCookie(PREFERENCES_COOKIE) || readStorage(PREFERENCES_KEY) || "{}"));
        categories.forEach((key) => { if (typeof stored[key] === "boolean") preferences[key] = stored[key]; });
    } catch (_) { /* Keep the conservative defaults if storage is unavailable or malformed. */ }
    const exposeChoice = (value) => {
        document.documentElement.dataset.cookieConsent = value;
        document.documentElement.dataset.cookieAnalytics = String(preferences.analytics);
        document.documentElement.dataset.cookieFunctional = String(preferences.functional);
        document.documentElement.dataset.cookieAdvertising = String(preferences.advertising);
    };
    if (["accepted", "declined", "custom"].includes(choice)) exposeChoice(choice);
    else window.requestAnimationFrame(() => banner.classList.add("is-visible"));
    const persist = (value, selected) => {
        preferences = selected;
        const suffix = "; Path=/; Max-Age=31536000; SameSite=Lax" + (location.protocol === "https:" ? "; Secure" : "");
        document.cookie = COOKIE_NAME + "=" + value + suffix;
        document.cookie = PREFERENCES_COOKIE + "=" + encodeURIComponent(JSON.stringify(selected)) + suffix;
        try { localStorage.setItem(STORAGE_KEY, value); localStorage.setItem(PREFERENCES_KEY, JSON.stringify(selected)); sessionStorage.setItem(STORAGE_KEY, value); } catch (_) { /* The persistent cookie remains the primary storage. */ }
        exposeChoice(value);
        document.dispatchEvent(new CustomEvent("cookie-consent:changed", { detail: { choice: value, preferences: { ...selected, necessary: true } } }));
        if (dialog.open) dialog.close();
        banner.classList.remove("is-visible");
    };
    const handleChoice = (event) => {
        const button = event.target.closest("[data-cookie-choice]");
        if (!button) return;
        const value = button.dataset.cookieChoice;
        if (!["accepted", "declined"].includes(value)) return;
        persist(value, Object.fromEntries(categories.map((key) => [key, value === "accepted"])));
    };
    banner.addEventListener("click", handleChoice);
    dialog.addEventListener("click", handleChoice);
    document.querySelectorAll("[data-cookie-settings]").forEach((button) => button.addEventListener("click", () => {
        controls.forEach((input) => { input.checked = preferences[input.dataset.cookieCategory]; });
        if (!dialog.open) dialog.showModal();
    }));
    dialog.querySelector("[data-cookie-close]").addEventListener("click", () => dialog.close());
    dialog.querySelector("[data-cookie-preferences-form]").addEventListener("submit", (event) => {
        event.preventDefault();
        const selected = Object.fromEntries(controls.map((input) => [input.dataset.cookieCategory, input.checked]));
        const values = Object.values(selected);
        persist(values.every(Boolean) ? "accepted" : values.some(Boolean) ? "custom" : "declined", selected);
    });
})();

(() => {
    const legacyBadges = document.querySelectorAll(
        ".forecast-verified, .verified-mark, .prediction-verified"
    );
    if (!legacyBadges.length) return;

    const badgeSvg = `
        <svg viewBox="0 0 16 16" aria-hidden="true">
            <path class="capper-verified-bg" d="M10.067.87a2.89 2.89 0 0 0-4.134 0l-.622.638-.89-.011a2.89 2.89 0 0 0-2.924 2.924l.01.89-.636.622a2.89 2.89 0 0 0 0 4.134l.637.622-.011.89a2.89 2.89 0 0 0 2.924 2.924l.89-.01.622.636a2.89 2.89 0 0 0 4.134 0l.622-.637.89.011a2.89 2.89 0 0 0 2.924-2.924l-.01-.89.636-.622a2.89 2.89 0 0 0 0-4.134l-.637-.622.011-.89a2.89 2.89 0 0 0-2.924-2.924l-.89.01z"></path>
            <path class="capper-verified-check" d="M10.354 6.854a.5.5 0 0 0-.708-.708L7 8.793 5.854 7.646a.5.5 0 1 0-.708.708l1.5 1.5a.5.5 0 0 0 .708 0z"></path>
        </svg>`;

    legacyBadges.forEach((badge) => {
        badge.className = "capper-verified-badge";
        badge.title = "Проверенный эксперт";
        badge.setAttribute("aria-label", "Проверенный эксперт");
        badge.innerHTML = badgeSvg;
    });
})();

(() => {
    const backLink = document.querySelector(".coupon-detail-back");
    if (!backLink) return;

    const label = backLink.querySelector("span:last-child");
    const currentUrl = new URL(window.location.href);
    const storageKey = `cappers:coupon-back:${currentUrl.pathname}`;
    const maxStoredAge = 30 * 60 * 1000;
    const matchDetailPath = /^\/games\/[^/]+\/?$/;

    const isSameLocation = (left, right) => (
        left.pathname === right.pathname
        && left.search === right.search
        && left.hash === right.hash
    );

    const isUsableSource = (url) => (
        url.origin === currentUrl.origin
        && !isSameLocation(url, currentUrl)
    );

    const sourceLabel = (url) => {
        const path = url.pathname;

        if (path === "/cabinet/profile/") {
            if (url.searchParams.get("tab") === "predictions") {
                return "Вернуться к моим купонам";
            }
            return "Вернуться в мой профиль";
        }
        if (/^\/experts\/[^/]+\/?$/.test(path)) {
            return "Вернуться к профилю каппера";
        }
        if (
            path === "/predictions/"
            || (/^\/predictions\/[^/]+\/?$/.test(path) && !/^\/predictions\/\d+\/?$/.test(path))
        ) {
            return "Вернуться к прогнозам";
        }
        if (path === "/feed/") {
            return url.searchParams.get("favorites") === "1"
                ? "Вернуться в избранное"
                : "Вернуться в мою ленту";
        }
        if (path === "/") {
            return "Вернуться на главную";
        }
        if (path.startsWith("/games/")) {
            const parts = path.split("/").filter(Boolean);
            return parts.length === 2 ? "Вернуться к матчу" : "Вернуться к матчам";
        }
        if (path === "/tournaments/") {
            return "Вернуться к турнирам";
        }
        if (path.startsWith("/tournaments/")) {
            return "Вернуться к турниру";
        }
        if (path.startsWith("/cappers-table/")) {
            return "Вернуться к капперам";
        }
        return "Вернуться назад";
    };

    const readStoredSource = () => {
        try {
            const raw = sessionStorage.getItem(storageKey);
            if (!raw) return null;
            const stored = JSON.parse(raw);
            const age = Date.now() - Number(stored?.savedAt || 0);
            if (!stored?.href || !stored?.savedAt || age < 0 || age > maxStoredAge) {
                sessionStorage.removeItem(storageKey);
                return null;
            }
            const url = new URL(stored.href, currentUrl.href);
            return isUsableSource(url) ? url : null;
        } catch (error) {
            return null;
        }
    };

    const storeSource = (url) => {
        try {
            sessionStorage.setItem(storageKey, JSON.stringify({
                href: url.href,
                savedAt: Date.now(),
            }));
        } catch (error) {
            // document.referrer remains enough when sessionStorage is unavailable.
        }
    };

    const consumeCouponMatchRoundTrip = (referrer) => {
        if (!matchDetailPath.test(referrer.pathname)) return false;

        const returnKey = `cappers:coupon-match-return:${referrer.pathname}`;
        try {
            const raw = sessionStorage.getItem(returnKey);
            if (!raw) return false;

            const stored = JSON.parse(raw);
            const age = Date.now() - Number(stored?.savedAt || 0);
            if (!stored?.couponHref || !stored?.savedAt || age < 0 || age > maxStoredAge) {
                sessionStorage.removeItem(returnKey);
                return false;
            }

            const couponUrl = new URL(stored.couponHref, currentUrl.href);
            if (couponUrl.origin !== currentUrl.origin || !isSameLocation(couponUrl, currentUrl)) return false;

            sessionStorage.removeItem(returnKey);
            return true;
        } catch (error) {
            return false;
        }
    };

    const isReturnFromMatch = (referrer) => {
        if (!matchDetailPath.test(referrer.pathname)) return false;
        if (consumeCouponMatchRoundTrip(referrer)) return true;

        try {
            const raw = sessionStorage.getItem(`cappers:match-back:${referrer.pathname}`);
            if (!raw) return false;

            const stored = JSON.parse(raw);
            const age = Date.now() - Number(stored?.savedAt || 0);
            if (!stored?.href || !stored?.savedAt || age < 0 || age > maxStoredAge) return false;

            const matchSource = new URL(stored.href, currentUrl.href);
            return matchSource.origin === currentUrl.origin && isSameLocation(matchSource, currentUrl);
        } catch (error) {
            return false;
        }
    };

    let defaultSource = null;
    try {
        const url = new URL(backLink.href, currentUrl.href);
        if (isUsableSource(url)) defaultSource = url;
    } catch (error) {
        defaultSource = null;
    }

    const storedSource = readStoredSource();
    const rememberedSource = storedSource || defaultSource;
    let source = null;

    if (document.referrer) {
        try {
            const referrer = new URL(document.referrer, currentUrl.href);
            if (isUsableSource(referrer)) {
                if (rememberedSource && isReturnFromMatch(referrer)) {
                    source = rememberedSource;
                } else {
                    source = referrer;
                    storeSource(referrer);
                }
            }
        } catch (error) {
            source = null;
        }
    }

    source = source || rememberedSource;
    if (!source) return;

    backLink.href = source.href;
    if (label) label.textContent = sourceLabel(source);
})();
