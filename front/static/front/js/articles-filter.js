(($) => {
    "use strict";

    if (!$) return;

    let activeRequest = null;
    let searchTimer = null;

    const getRoot = () => $("[data-articles-page]").first();
    const getResults = () => $("[data-articles-results]").first();
    const getForm = () => $("[data-articles-filter-form]").first();

    const buildUrl = (options = {}) => {
        const $form = getForm();
        const baseUrl = $form.attr("action") || window.location.pathname;
        const params = new URLSearchParams();
        const query = ($form.find("[name='q']").val() || "").trim();
        const category = options.category ?? ($form.find("[name='category']").val() || "");
        const sort =
            options.sort ??
            (getResults().find("[data-articles-sort]").val() || $form.find("[name='sort']").val() || "new");
        const page = options.page || "";

        if (query) params.set("q", query);
        if (category) params.set("category", category);
        if (sort && sort !== "new") params.set("sort", sort);
        if (page) params.set("page", page);

        const queryString = params.toString();
        return queryString ? `${baseUrl}?${queryString}` : baseUrl;
    };

    const setLoading = (loading) => {
        const $root = getRoot();
        $root.toggleClass("is-loading", loading);
        $root.attr("aria-busy", loading ? "true" : "false");
    };

    const syncFormFromUrl = (url) => {
        const parsedUrl = new URL(url, window.location.origin);
        const $form = getForm();
        $form.find("[name='q']").val(parsedUrl.searchParams.get("q") || "");
        $form.find("[name='category']").val(parsedUrl.searchParams.get("category") || "");
        $form.find("[name='sort']").val(parsedUrl.searchParams.get("sort") || "new");
    };

    const loadResults = (url, options = {}) => {
        const $results = getResults();
        if (!$results.length) {
            window.location.assign(url);
            return;
        }

        if (activeRequest) activeRequest.abort();
        setLoading(true);

        activeRequest = $.ajax({
            url,
            method: "GET",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        })
            .done((response) => {
                if (!response || typeof response.html !== "string") {
                    window.location.assign(url);
                    return;
                }

                $results.html(response.html);
                if (options.category !== undefined) {
                    getForm().find("[name='category']").val(options.category);
                }
                const selectedSort = getResults().find("[data-articles-sort]").val() || "new";
                getForm().find("[name='sort']").val(selectedSort);
                syncFormFromUrl(url);
                if (options.pushState !== false) {
                    window.history.pushState({}, "", url);
                }
            })
            .fail((xhr, status) => {
                if (status !== "abort") window.location.assign(url);
            })
            .always(() => {
                activeRequest = null;
                setLoading(false);
            });
    };

    $(document).on("submit", "[data-articles-filter-form]", (event) => {
        event.preventDefault();
        loadResults(buildUrl());
    });

    $(document).on("input", "[data-articles-search]", () => {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => {
            loadResults(buildUrl());
        }, 320);
    });

    $(document).on("click", "[data-articles-category-link]", function handleCategory(event) {
        event.preventDefault();
        const category = $(this).data("category") || "";
        loadResults(buildUrl({ category }), { category });
    });

    $(document).on("change", "[data-articles-sort]", function handleSort() {
        const sort = $(this).val() || "new";
        getForm().find("[name='sort']").val(sort);
        loadResults(buildUrl({ sort }));
    });

    $(document).on("click", "[data-articles-page-link]", function handlePagination(event) {
        event.preventDefault();
        loadResults(this.href);
    });

    window.addEventListener("popstate", () => {
        loadResults(window.location.href, { pushState: false });
    });
})(window.jQuery);
