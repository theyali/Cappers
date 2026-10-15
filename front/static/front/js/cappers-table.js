(function () {
    const REGION_SELECTOR = "[data-cappers-ranking-region]";
    const TITLE_SELECTOR = "[data-cappers-table-title]";
    const BASE_TITLE = "Таблица капперов";
    let activeRequest = null;

    function withPartialParam(url, preserveSearch) {
        const nextUrl = new URL(url, window.location.origin);
        nextUrl.searchParams.set("partial", "ranking");

        const searchInput = document.querySelector(`${REGION_SELECTOR} input[name="q"]`);
        if (preserveSearch && searchInput) {
            const query = searchInput.value.trim();
            if (query) nextUrl.searchParams.set("q", query);
            else nextUrl.searchParams.delete("q");
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

        const requestUrl = withPartialParam(url, pushState);
        if (activeRequest) activeRequest.abort();
        const controller = new AbortController();
        activeRequest = controller;
        const restoreFocus = region.contains(document.activeElement);
        region.setAttribute("aria-busy", "true");
        region.classList.add("is-loading");

        try {
            const response = await fetch(requestUrl.toString(), {
                signal: controller.signal,
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            if (controller.signal.aborted || activeRequest !== controller) return true;
            if (!response.ok) {
                return false;
            }

            const html = await response.text();
            // An obsolete response must not replace a newer period or navigate away.
            if (controller.signal.aborted || activeRequest !== controller) return true;
            const template = document.createElement("template");
            template.innerHTML = html.trim();
            const nextRegion = template.content.querySelector(REGION_SELECTOR);
            if (!nextRegion) {
                return false;
            }

            region.replaceWith(nextRegion);
            if (restoreFocus) nextRegion.querySelector(".cappers-period-filter summary")?.focus({ preventScroll: true });
            updateTitle(nextRegion);
            if (pushState) {
                const nextUrl = cleanUrl(requestUrl).toString();
                window.history.pushState({ cappersRankingUrl: nextUrl }, "", nextUrl);
            }
            return true;
        } catch (error) {
            return controller.signal.aborted || activeRequest !== controller;
        } finally {
            const activeRegion = document.querySelector(REGION_SELECTOR);
            if (activeRequest === controller) {
                if (activeRegion) {
                    activeRegion.removeAttribute("aria-busy");
                    activeRegion.classList.remove("is-loading");
                }
                activeRequest = null;
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
        title.textContent = "";
        title.append("Таблица ");
        const accent = document.createElement("span");
        accent.textContent = "капперов";
        title.append(accent);
        if (monthLabel && monthLabel !== "Все время") {
            title.append(` — ${monthLabel}`);
        }
        document.title = `${nextTitle} — КапперХаб`;
    }

    document.addEventListener("click", function (event) {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
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
        replaceRanking(window.location.href, false).then(function (handled) {
            if (!handled) window.location.reload();
        });
    });
})();
