(($) => {
    "use strict";

    if (!$) return;

    let activeRequest = null;
    let filterTimer = null;

    const currentLayout = () => $("[data-predictions-layout]").first();

    const setSidebarCollapsed = (collapsed) => {
        const $layout = currentLayout();
        if (!$layout.length) return;

        $layout.toggleClass("is-filter-collapsed", collapsed);
        const $toggle = $layout.find("[data-prediction-filter-toggle]").first();
        $toggle.attr("aria-expanded", collapsed ? "false" : "true");
    };

    const responseDocument = (html) => {
        const nodes = $.parseHTML(html, document, true);
        return $("<div>").append(nodes);
    };

    const syncHeroTotal = ($response) => {
        const value = $response.find("[data-predictions-total-value]").first().text();
        if (value !== "") {
            $("[data-predictions-total-value]").first().text(value);
        }
    };

    const animateIncomingResults = () => {
        const $content = currentLayout().find("[data-predictions-content]").first();
        if (!$content.length) return;

        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
                $content.removeClass("is-results-entering");
            });
        });
    };

    const loadPredictions = (url, options = {}) => {
        const $layout = currentLayout();
        if (!$layout.length) {
            window.location.assign(url);
            return;
        }

        const wasCollapsed = $layout.hasClass("is-filter-collapsed");
        const $content = $layout.find("[data-predictions-content]").first();
        const $sort = $layout.find("[data-prediction-sort]").first();

        $layout.addClass("is-loading");
        $content.addClass("is-results-leaving");

        if (options.sortChange) {
            $sort.addClass("is-changing").prop("disabled", true);
        }

        if (activeRequest) activeRequest.abort();

        const request = $.ajax({
            url,
            method: "GET",
            dataType: "html",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        });
        activeRequest = request;

        request
            .done((html) => {
                const $response = responseDocument(html);
                const $nextLayout = $response.find("[data-predictions-layout]").first();

                if (!$nextLayout.length) {
                    window.location.assign(url);
                    return;
                }

                $nextLayout.find("[data-predictions-content]").first().addClass("is-results-entering");
                $layout.replaceWith($nextLayout);
                syncHeroTotal($response);
                setSidebarCollapsed(wasCollapsed);
                animateIncomingResults();

                if (options.pushState !== false) {
                    window.history.pushState({}, "", url);
                }

                document.dispatchEvent(new CustomEvent("predictions:updated"));
            })
            .fail((xhr, status) => {
                if (status !== "abort") window.location.assign(url);
            })
            .always(() => {
                if (activeRequest === request) activeRequest = null;
                currentLayout().removeClass("is-loading");
            });
    };

    const formUrl = ($form) => {
        const params = new URLSearchParams($form.serialize());
        params.delete("page");
        const query = params.toString();
        const action = $form.attr("action") || window.location.pathname;
        return query ? `${action}?${query}` : action;
    };

    const sortUrl = (value) => {
        const url = new URL(window.location.href);
        url.searchParams.set("sort", value || "new");
        url.searchParams.delete("page");
        return url.href;
    };

    const scheduleFormSubmit = ($form, delay) => {
        window.clearTimeout(filterTimer);
        filterTimer = window.setTimeout(() => {
            filterTimer = null;
            $form.trigger("submit");
        }, delay);
    };

    $(document).on("click", "[data-prediction-filter-toggle]", (event) => {
        event.preventDefault();
        const $layout = currentLayout();
        setSidebarCollapsed(!$layout.hasClass("is-filter-collapsed"));
    });

    $(document).on("submit", "[data-prediction-filters]", function (event) {
        event.preventDefault();
        loadPredictions(formUrl($(this)));
    });

    $(document).on(
        "change",
        "[data-prediction-filters] select, [data-prediction-filters] input[type='checkbox']",
        function () {
            const $form = $(this).closest("[data-prediction-filters]");
            if (this.name === "sport") $form.find("[name='league']").val("");
            $form.trigger("submit");
        }
    );

    $(document).on(
        "input",
        "[data-prediction-filters] input[type='number'], [data-prediction-filters] input[type='search']",
        function () {
            const $form = $(this).closest("[data-prediction-filters]");
            scheduleFormSubmit($form, this.type === "search" ? 300 : 350);
        }
    );

    $(document).on("change", "[data-prediction-sort]", function () {
        loadPredictions(sortUrl(this.value), { sortChange: true });
    });

    $(document).on(
        "click",
        ".predictions-tabs a, .predictions-pagination a, .prediction-filter-reset, [data-prediction-ajax-link]",
        function (event) {
            const href = this.href;
            if (!href) return;

            const target = new URL(href, window.location.href);
            if (target.origin !== window.location.origin) return;

            event.preventDefault();
            loadPredictions(target.href);
        }
    );

    window.addEventListener("popstate", () => {
        loadPredictions(window.location.href, { pushState: false });
    });
})(window.jQuery);
