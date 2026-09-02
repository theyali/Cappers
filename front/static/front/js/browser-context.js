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
