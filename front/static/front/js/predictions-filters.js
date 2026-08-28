(($) => {
    "use strict";

    if (!$) return;

    let activeRequest = null;

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

    const loadPredictions = (url, options = {}) => {
        const $layout = currentLayout();
        if (!$layout.length) {
            window.location.assign(url);
            return;
        }

        const wasCollapsed = $layout.hasClass("is-filter-collapsed");
        $layout.addClass("is-loading");

        if (activeRequest) activeRequest.abort();

        activeRequest = $.ajax({
            url,
            method: "GET",
            dataType: "html",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        })
            .done((html) => {
                const $response = responseDocument(html);
                const $nextLayout = $response.find("[data-predictions-layout]").first();

                if (!$nextLayout.length) {
                    window.location.assign(url);
                    return;
                }

                $layout.replaceWith($nextLayout);
                syncHeroTotal($response);
                setSidebarCollapsed(wasCollapsed);

                if (options.pushState !== false) {
                    window.history.pushState({}, "", url);
                }

                document.dispatchEvent(new CustomEvent("predictions:updated"));
            })
            .fail((xhr, status) => {
                if (status !== "abort") window.location.assign(url);
            })
            .always(() => {
                activeRequest = null;
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

    $(document).on("change", "[data-prediction-sort]", function () {
        loadPredictions(sortUrl(this.value));
    });

    $(document).on("click", ".predictions-tabs a, .predictions-pagination a, .prediction-filter-reset", function (event) {
        const href = this.href;
        if (!href) return;

        const target = new URL(href, window.location.href);
        if (target.origin !== window.location.origin) return;

        event.preventDefault();
        loadPredictions(target.href);
    });

    window.addEventListener("popstate", () => {
        loadPredictions(window.location.href, { pushState: false });
    });
})(window.jQuery);
