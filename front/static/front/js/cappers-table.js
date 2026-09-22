(function () {
    const REGION_SELECTOR = "[data-cappers-ranking-region]";
    const TITLE_SELECTOR = "[data-cappers-table-title]";
    const BASE_TITLE = "Таблица капперов";

    function withPartialParam(url) {
        const nextUrl = new URL(url, window.location.origin);
        nextUrl.searchParams.set("partial", "ranking");

        const searchInput = document.querySelector(`${REGION_SELECTOR} input[name="q"]`);
        if (searchInput && searchInput.value.trim()) {
            nextUrl.searchParams.set("q", searchInput.value.trim());
        }

        return nextUrl;
    }

    function cleanUrl(url) {
        const clean = new URL(url, window.location.origin);
        clean.searchParams.delete("partial");
        return clean;
    }

    async function replaceRanking(url, pushState) {
        const region = document.querySelector(REGION_SELECTOR);
        if (!region) {
            return false;
        }

        const requestUrl = withPartialParam(url);
        region.setAttribute("aria-busy", "true");
        region.classList.add("is-loading");

        try {
            const response = await fetch(requestUrl.toString(), {
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            if (!response.ok) {
                return false;
            }

            const html = await response.text();
            const template = document.createElement("template");
            template.innerHTML = html.trim();
            const nextRegion = template.content.querySelector(REGION_SELECTOR);
            if (!nextRegion) {
                return false;
            }

            region.replaceWith(nextRegion);
            updateTitle(nextRegion);
            if (pushState) {
                window.history.pushState({ cappersRankingUrl: cleanUrl(url).toString() }, "", cleanUrl(url).toString());
            }
            return true;
        } catch (error) {
            return false;
        } finally {
            const activeRegion = document.querySelector(REGION_SELECTOR);
            if (activeRegion) {
                activeRegion.removeAttribute("aria-busy");
                activeRegion.classList.remove("is-loading");
            }
        }
    }

    function updateTitle(region) {
        const title = document.querySelector(TITLE_SELECTOR);
        if (!title || !region) return;

        const monthLabel = (region.dataset.selectedMonthLabel || "").trim();
        const nextTitle = monthLabel && monthLabel !== "Все время"
            ? `${BASE_TITLE} — ${monthLabel}`
            : BASE_TITLE;
        title.textContent = nextTitle;
        document.title = `${nextTitle} — КапперХаб`;
    }

    document.addEventListener("click", function (event) {
        const link = event.target.closest(".cappers-period-menu a");
        if (!link || !document.querySelector(REGION_SELECTOR)) {
            return;
        }

        const url = new URL(link.href, window.location.origin);
        if (url.origin !== window.location.origin) {
            return;
        }

        event.preventDefault();
        event.stopImmediatePropagation();
        replaceRanking(url, true).then(function (handled) {
            if (!handled) {
                window.location.href = link.href;
            }
        });
    }, true);

    window.addEventListener("popstate", function () {
        replaceRanking(window.location.href, false);
    });
})();
