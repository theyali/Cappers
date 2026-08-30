(($) => {
    "use strict";

    if (!$) return;

    const PAGE_SELECTOR = ".matches-page";
    const LINK_SELECTOR = [
        ".matches-table-filter-sidebar a[href]",
        ".matches-sport-tabs a[href]",
        ".matches-tabs a[href]",
        ".matches-date-filter a[href]",
    ].join(",");
    const MOBILE_FILTER_BLOCK_SELECTOR = ".matches-mobile-scope-panel, .matches-mobile-sports-panel";

    let activeRequest = null;
    let activeSeq = 0;

    const setMobileFiltersLoading = ($page) => {
        $page.find(MOBILE_FILTER_BLOCK_SELECTOR).each((_index, block) => {
            window.CappersSkeleton?.loading(block);
        });
    };

    const setMobileFiltersReady = ($page) => {
        $page.find(MOBILE_FILTER_BLOCK_SELECTOR).each((_index, block) => {
            window.CappersSkeleton?.ready(block);
        });
    };

    const sameOriginPath = (rawUrl) => {
        const url = new URL(rawUrl, window.location.origin);
        if (url.origin !== window.location.origin) return null;
        return url;
    };

    const partialUrl = (rawUrl) => {
        const url = sameOriginPath(rawUrl);
        if (!url) return null;
        url.searchParams.delete("lazy");
        url.searchParams.delete("page");
        url.searchParams.delete("window");
        url.searchParams.delete("view");
        url.searchParams.delete("table_sport");
        url.searchParams.set("partial", "matches");
        return url;
    };

    const publicUrl = (payload, fallbackUrl) => {
        const url = payload?.url ? new URL(payload.url, window.location.origin) : fallbackUrl;
        url.searchParams.delete("partial");
        return `${url.pathname}${url.search}${url.hash}`;
    };

    const replaceHeadMeta = (payload) => {
        if (payload.title) document.title = payload.title;
        const meta = payload.meta || {};

        const setMeta = (selector, attr, value) => {
            if (value === undefined || value === null) return;
            const node = document.head.querySelector(selector);
            if (node) node.setAttribute(attr, value);
        };

        setMeta('meta[name="description"]', "content", meta.description);
        setMeta('meta[name="robots"]', "content", meta.robots);
        setMeta('link[rel="canonical"]', "href", meta.canonical_url);
        setMeta('meta[property="og:title"]', "content", meta.og_title);
        setMeta('meta[property="og:description"]', "content", meta.og_description);
        setMeta('meta[property="og:url"]', "content", meta.og_url);
        setMeta('meta[name="twitter:title"]', "content", meta.twitter_title);
        setMeta('meta[name="twitter:description"]', "content", meta.twitter_description);
    };

    const replaceNode = ($current, html, selector) => {
        if (!$current.length || typeof html !== "string") return $();
        const $next = $(html.trim());
        if (!$next.length || (selector && !$next.is(selector))) return $();
        $current.replaceWith($next);
        return $next;
    };

    const replaceWithFade = ($current, html, selector) => {
        if (!$current.length || typeof html !== "string") return $();
        const height = $current.outerHeight();
        if (height) $current.css("min-height", `${height}px`);
        $current.addClass("is-ajax-leaving");

        const $next = $(html.trim());
        if (!$next.length || (selector && !$next.is(selector))) {
            $current.removeClass("is-ajax-leaving").css("min-height", "");
            return $();
        }

        $next.addClass("is-ajax-entering");
        $current.replaceWith($next);
        window.requestAnimationFrame(() => {
            $next.removeClass("is-ajax-entering");
            window.CappersSkeleton?.watchImages($next.get(0));
        });
        return $next;
    };

    const dispatchUpdated = ($page, $content) => {
        const nodes = Array.from($content.find("[data-match-shell-id]"));
        document.dispatchEvent(new CustomEvent("matches:filters-updated", {
            detail: {
                page: $page.get(0),
                root: $content.get(0),
                nodes,
            },
        }));
        if (nodes.length) {
            document.dispatchEvent(new CustomEvent("matches:appended", { detail: { nodes } }));
        }
    };

    const applyPayload = (payload, fallbackUrl, { push = true } = {}) => {
        const $page = $(PAGE_SELECTOR).first();
        if (!$page.length || !payload?.ok) return;

        const $listPanel = $page.find(".matches-list-panel").first();
        replaceNode($page.children(".matches-sport-tabs").first(), payload.sport_tabs_html, ".matches-sport-tabs");
        replaceNode($page.children(".matches-tabs").first(), payload.scope_tabs_html, ".matches-tabs");
        replaceNode($page.find(".matches-mobile-sports-panel > .matches-sport-tabs").first(), payload.sport_tabs_html, ".matches-sport-tabs");
        replaceNode($page.find(".matches-mobile-scope-panel > .matches-tabs").first(), payload.scope_tabs_html, ".matches-tabs");

        const $dateFilter = $page.children(".matches-date-filter").first();
        if (payload.date_filter_html && payload.date_filter_html.trim()) {
            if ($dateFilter.length) {
                replaceNode($dateFilter, payload.date_filter_html, ".matches-date-filter");
            } else {
                $page.children(".matches-tabs").first().after(payload.date_filter_html);
            }
        } else {
            $dateFilter.remove();
        }

        replaceNode($page.find(".matches-table-filter-sidebar").first(), payload.sidebar_html, ".matches-table-filter-sidebar");
        const $hero = replaceWithFade($listPanel.children(".matches-hero").first(), payload.hero_html, ".matches-hero");
        const $content = replaceWithFade($listPanel.children("[data-matches-content-region]").first(), payload.content_html, "[data-matches-content-region]");

        const mode = payload.content_view_mode || $listPanel.attr("data-content-view-current") || "grid";
        $listPanel.attr("data-content-view-current", mode);
        if ($hero.length) $hero.attr("aria-busy", "false").removeClass("is-skeleton-loading");

        setMobileFiltersReady($page);
        replaceHeadMeta(payload);

        const nextUrl = publicUrl(payload, fallbackUrl);
        if (push && nextUrl !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
            window.history.pushState({ matchesFilterUrl: nextUrl }, "", nextUrl);
        }

        const panel = $listPanel.get(0);
        if (panel) panel.scrollTo({ top: 0, behavior: "smooth" });
        dispatchUpdated($page, $content.length ? $content : $listPanel);
    };

    const go = (rawUrl, options = {}) => {
        const requestUrl = partialUrl(rawUrl);
        if (!requestUrl) {
            window.location.assign(rawUrl);
            return null;
        }

        const seq = ++activeSeq;
        const $page = $(PAGE_SELECTOR).first();
        if (activeRequest) activeRequest.abort();

        $page.addClass("is-filter-loading");
        setMobileFiltersLoading($page);
        activeRequest = $.ajax({
            url: `${requestUrl.pathname}${requestUrl.search}`,
            method: "GET",
            dataType: "json",
            cache: false,
            headers: {
                Accept: "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        });

        activeRequest
            .done((payload) => {
                if (seq !== activeSeq) return;
                applyPayload(payload, requestUrl, options);
            })
            .fail((_xhr, statusText) => {
                if (statusText === "abort") return;
                window.location.assign(rawUrl);
            })
            .always(() => {
                if (seq !== activeSeq) return;
                activeRequest = null;
                $page.removeClass("is-filter-loading");
            });

        return activeRequest;
    };

    $(document).on("click", LINK_SELECTOR, function (event) {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
        const href = this.getAttribute("href");
        if (!href || this.hasAttribute("download") || this.target) return;
        const url = sameOriginPath(href);
        if (!url || !url.pathname.startsWith("/games/")) return;

        event.preventDefault();
        go(url.toString());
    });

    window.addEventListener("popstate", () => {
        go(window.location.href, { push: false });
    });

    window.CappersMatchesFilterAjax = { go };
})(window.jQuery);
