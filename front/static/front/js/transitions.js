(() => {
    const overlay = document.querySelector(".logo-transition");
    if (!overlay) return;

    let isLeaving = false;

    const showTransition = () => {
        if (isLeaving) return;
        isLeaving = true;
        overlay.classList.add("is-active");
    };

    const transitionDuration = 420;

    const isModifiedClick = (event) => (
        event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0
    );

    document.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        if (!link || isModifiedClick(event)) return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download")) return;
        if (link.hasAttribute("data-profile-tab-link")) return;
        if (link.closest(".matches-table-filter-sidebar, .matches-sport-tabs, .matches-tabs, .matches-date-filter")) return;
        if (link.hasAttribute("data-mobile-coupon-toggle")) {
            event.preventDefault();
            return;
        }

        const url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin) return;
        if (url.pathname === window.location.pathname && url.search === window.location.search) return;
        if (url.hash && url.pathname === window.location.pathname && url.search === window.location.search) return;

        event.preventDefault();
        showTransition();
        window.setTimeout(() => {
            window.location.href = url.href;
        }, transitionDuration);
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (event.defaultPrevented) return;
        if (form.matches("[data-no-transition]")) return;
        if (form.dataset.transitionSubmitted === "true") return;

        event.preventDefault();
        form.dataset.transitionSubmitted = "true";
        showTransition();
        window.setTimeout(() => {
            form.submit();
        }, transitionDuration);
    });

    window.addEventListener("pageshow", () => {
        isLeaving = false;
        overlay.classList.remove("is-active");
    });
})();

(() => {
    const COOKIE_NAME = "capperhub_cookie_consent";
    const STORAGE_KEY = "capperhub.cookieConsent";
    const VALID_CHOICES = new Set(["accepted", "declined"]);

    const readCookie = () => {
        const prefix = `${COOKIE_NAME}=`;
        const value = document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
        return VALID_CHOICES.has(value) ? value : "";
    };

    const readChoice = () => {
        const cookieChoice = readCookie();
        if (cookieChoice) return cookieChoice;
        try {
            const stored = sessionStorage.getItem(STORAGE_KEY) || "";
            return VALID_CHOICES.has(stored) ? stored : "";
        } catch (error) {
            return "";
        }
    };

    const exposeChoice = (choice) => {
        if (!choice) return;
        document.documentElement.dataset.cookieConsent = choice;
    };

    const existingChoice = readChoice();
    if (existingChoice) {
        exposeChoice(existingChoice);
        return;
    }

    const banner = document.createElement("section");
    banner.className = "cookie-consent";
    banner.dataset.cookieConsent = "";
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-live", "polite");
    banner.setAttribute("aria-label", "Настройки cookies");
    banner.innerHTML = `
        <div class="cookie-consent-copy">
            <strong>Cookies на КапперХаб</strong>
            <p>Используем технические cookies для работы сайта. Необязательные cookies можно принять или отклонить.</p>
        </div>
        <div class="cookie-consent-actions">
            <button class="cookie-consent-button" type="button" data-cookie-choice="declined">Отклонить</button>
            <button class="cookie-consent-button is-accept" type="button" data-cookie-choice="accepted">Принять</button>
        </div>`;
    document.body.appendChild(banner);

    const saveChoice = (choice) => {
        document.cookie = `${COOKIE_NAME}=${choice}; Path=/; SameSite=Lax`;
        try {
            sessionStorage.setItem(STORAGE_KEY, choice);
        } catch (error) {
            // Session cookie remains the primary storage when sessionStorage is unavailable.
        }
        exposeChoice(choice);
        document.dispatchEvent(new CustomEvent("cookie-consent:changed", {
            detail: { choice },
        }));
    };

    const closeBanner = () => {
        banner.classList.remove("is-visible");
        window.setTimeout(() => banner.remove(), 210);
    };

    banner.addEventListener("click", (event) => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest("[data-cookie-choice]");
        if (!button) return;
        const choice = button.dataset.cookieChoice;
        if (!VALID_CHOICES.has(choice)) return;
        saveChoice(choice);
        closeBanner();
    });

    window.requestAnimationFrame(() => {
        banner.classList.add("is-visible");
    });
})();

(() => {
    const legacyBadges = document.querySelectorAll(
        ".forecast-verified, .verified-mark, .prediction-verified, .home-best-expert-verified"
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

    const isUsableSource = (url) => (
        url.origin === currentUrl.origin
        && !(url.pathname === currentUrl.pathname && url.search === currentUrl.search)
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
        if (path === "/favorites/") {
            return "Вернуться в избранное";
        }
        if (path === "/feed/") {
            return "Вернуться в мою ленту";
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
        if (path.startsWith("/cappers-statistics/") || path.startsWith("/cappers-table/")) {
            return "Вернуться к капперам";
        }
        return "Вернуться назад";
    };

    const readStoredSource = () => {
        try {
            const raw = sessionStorage.getItem(storageKey);
            if (!raw) return null;
            const stored = JSON.parse(raw);
            if (!stored?.href || !stored?.savedAt || Date.now() - stored.savedAt > maxStoredAge) {
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

    let source = null;
    if (document.referrer) {
        try {
            const referrer = new URL(document.referrer, currentUrl.href);
            if (isUsableSource(referrer)) {
                source = referrer;
                storeSource(referrer);
            }
        } catch (error) {
            source = null;
        }
    }

    source = source || readStoredSource();
    if (!source) return;

    backLink.href = source.href;
    if (label) label.textContent = sourceLabel(source);
})();
