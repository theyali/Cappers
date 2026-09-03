(() => {
    try {
        const timezoneName = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (!timezoneName) return;

        const cookieName = "cappers_tz";
        let currentTimezone = "";
        const cookieParts = document.cookie.split(";");
        for (let index = 0; index < cookieParts.length; index += 1) {
            const part = cookieParts[index].trim();
            if (part.startsWith(`${cookieName}=`)) {
                currentTimezone = decodeURIComponent(part.slice(cookieName.length + 1));
                break;
            }
        }

        const reloadKey = `cappers:tz-reload:${timezoneName}`;
        if (currentTimezone === timezoneName) {
            try {
                sessionStorage.removeItem(reloadKey);
            } catch (error) {
                // Cookies are sufficient when sessionStorage is unavailable.
            }
            return;
        }

        const secure = location.protocol === "https:" ? "; Secure" : "";
        document.cookie = `${cookieName}=${encodeURIComponent(timezoneName)}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;

        try {
            if (sessionStorage.getItem(reloadKey) === "1") return;
            sessionStorage.setItem(reloadKey, "1");
        } catch (error) {
            // Reload once even when sessionStorage is unavailable.
        }
        location.reload();
    } catch (error) {
        // Browser timezone detection must never break page rendering.
    }
})();

(() => {
    try {
        if (!window.sessionStorage) return;
        if ("scrollRestoration" in history) history.scrollRestoration = "manual";

        const key = `cappers:scroll:${location.pathname}${location.search}`;
        const savedY = Number.parseInt(sessionStorage.getItem(key) || "", 10);
        const hasSavedPosition = Number.isFinite(savedY) && savedY > 0;
        const savePosition = () => {
            try {
                sessionStorage.setItem(
                    key,
                    String(Math.max(0, window.scrollY || document.documentElement.scrollTop || 0))
                );
            } catch (error) {
                // Scroll restoration remains optional when storage is unavailable.
            }
        };

        window.addEventListener("pagehide", savePosition);
        window.addEventListener("beforeunload", savePosition);
        if (!hasSavedPosition) return;

        document.documentElement.setAttribute("data-scroll-restoring", "true");
        const style = document.createElement("style");
        style.textContent = "html[data-scroll-restoring] body{visibility:hidden;}";
        document.head.appendChild(style);

        let tries = 0;
        const release = () => {
            document.documentElement.removeAttribute("data-scroll-restoring");
        };
        const restore = () => {
            tries += 1;
            window.scrollTo(0, savedY);
            if (tries < 12 && Math.abs((window.scrollY || 0) - savedY) > 2) {
                window.requestAnimationFrame(restore);
                return;
            }
            release();
        };

        if (document.readyState === "loading") {
            document.addEventListener(
                "DOMContentLoaded",
                () => window.requestAnimationFrame(restore),
                { once: true }
            );
        } else {
            window.requestAnimationFrame(restore);
        }

        window.addEventListener(
            "load",
            () => {
                restore();
                window.setTimeout(release, 80);
            },
            { once: true }
        );
        window.setTimeout(release, 1200);
    } catch (error) {
        document.documentElement.removeAttribute("data-scroll-restoring");
    }
})();

(() => {
    const matchDetailPath = /^\/games\/[^/]+\/?$/;
    const maxStoredAge = 30 * 60 * 1000;
    const freshNavigationAge = 15 * 1000;

    const storageKey = (pathname) => `cappers:match-back:${pathname}`;
    const isMatchDetail = (url) => url.origin === window.location.origin && matchDetailPath.test(url.pathname);
    const isSameLocation = (left, right) => (
        left.pathname === right.pathname
        && left.search === right.search
        && left.hash === right.hash
    );

    const writeSource = (targetUrl, sourceUrl) => {
        if (!isMatchDetail(targetUrl)) return;
        if (sourceUrl.origin !== targetUrl.origin || isSameLocation(sourceUrl, targetUrl)) return;
        try {
            sessionStorage.setItem(storageKey(targetUrl.pathname), JSON.stringify({
                href: sourceUrl.href,
                savedAt: Date.now(),
            }));
        } catch (error) {
            // document.referrer remains the fallback when sessionStorage is unavailable.
        }
    };

    document.addEventListener("click", (event) => {
        if (!(event.target instanceof Element)) return;
        const link = event.target.closest("a[href]");
        if (!link || link.hasAttribute("download")) return;
        try {
            const targetUrl = new URL(link.href, window.location.href);
            const sourceUrl = new URL(window.location.href);
            writeSource(targetUrl, sourceUrl);
        } catch (error) {
            // Ignore malformed href values.
        }
    }, true);

    const initBackLink = () => {
        const backLink = document.querySelector(".match-back-link");
        if (!backLink) return;

        const currentUrl = new URL(window.location.href);
        if (!isMatchDetail(currentUrl)) return;

        const isUsableSource = (url) => (
            url.origin === currentUrl.origin
            && !isSameLocation(url, currentUrl)
        );

        const sourceLabel = (url) => {
            const path = url.pathname;

            if (path === "/games/") return "Все матчи";
            if (matchDetailPath.test(path)) return "Вернуться к матчу";
            if (/^\/predictions\/\d+\/?$/.test(path)) return "Вернуться к прогнозу";
            if (/^\/cabinet\/coupons\/\d+\/?$/.test(path)) return "Вернуться к моему купону";
            if (
                path === "/predictions/"
                || (/^\/predictions\/[^/]+\/?$/.test(path) && !/^\/predictions\/\d+\/?$/.test(path))
            ) {
                return "Вернуться к прогнозам";
            }
            if (path === "/cabinet/profile/") {
                return url.searchParams.get("tab") === "predictions"
                    ? "Вернуться к моим купонам"
                    : "Вернуться в мой профиль";
            }
            if (/^\/experts\/[^/]+\/?$/.test(path)) return "Вернуться к профилю каппера";
            if (path === "/favorites/") return "Вернуться в избранное";
            if (path === "/feed/") return "Вернуться в мою ленту";
            if (path === "/tournaments/") return "Вернуться к турнирам";
            if (path.startsWith("/tournaments/")) return "Вернуться к турниру";
            if (path === "/cappers/" || path.startsWith("/cappers-statistics/") || path.startsWith("/cappers-table/")) {
                return "Вернуться к капперам";
            }
            if (path === "/") return "Вернуться на главную";
            return "Вернуться назад";
        };

        const readStoredSource = () => {
            try {
                const raw = sessionStorage.getItem(storageKey(currentUrl.pathname));
                if (!raw) return null;
                const stored = JSON.parse(raw);
                const age = Date.now() - Number(stored?.savedAt || 0);
                if (!stored?.href || !stored?.savedAt || age < 0 || age > maxStoredAge) {
                    sessionStorage.removeItem(storageKey(currentUrl.pathname));
                    return null;
                }
                const url = new URL(stored.href, currentUrl.href);
                if (!isUsableSource(url)) return null;
                return { url, age };
            } catch (error) {
                return null;
            }
        };

        let source = null;
        if (document.referrer) {
            try {
                const referrer = new URL(document.referrer, currentUrl.href);
                if (isUsableSource(referrer)) {
                    source = referrer;
                    writeSource(currentUrl, referrer);
                }
            } catch (error) {
                source = null;
            }
        }

        if (!source) {
            const stored = readStoredSource();
            if (stored) {
                const navigation = performance.getEntriesByType?.("navigation")?.[0];
                const navigationType = navigation?.type || "navigate";
                if (
                    navigationType === "reload"
                    || navigationType === "back_forward"
                    || stored.age <= freshNavigationAge
                ) {
                    source = stored.url;
                }
            }
        }

        if (!source) return;
        backLink.href = source.href;
        backLink.textContent = `← ${sourceLabel(source)}`;
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initBackLink, { once: true });
    } else {
        initBackLink();
    }
})();
