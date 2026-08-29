(($) => {
    "use strict";

    if (!$) return;

    let activeRequest = null;

    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const persistMode = ($switcher, mode) => {
        const stateUrl = $switcher.data("stateUrl");
        if (!stateUrl) return;

        $.ajax({
            url: stateUrl,
            method: "POST",
            dataType: "json",
            data: { mode },
            headers: {
                "X-CSRFToken": decodeURIComponent(getCookie("csrftoken")),
                "X-Requested-With": "XMLHttpRequest",
            },
        });
    };

    const requestUrl = (mode) => {
        const url = new URL(window.location.href);
        url.searchParams.set("view_mode", mode);
        url.searchParams.set("view_fragment", "1");
        return url.href;
    };

    const setButtons = ($switcher, mode, disabled = false) => {
        $switcher.find("[data-content-view-mode]").each(function () {
            const $button = $(this);
            const active = $button.data("contentViewMode") === mode;
            $button.toggleClass("is-active", active);
            $button.attr("aria-pressed", active ? "true" : "false");
            $button.prop("disabled", disabled);
        });
    };

    const finish = ($container) => {
        window.CappersSkeleton?.ready($container.get(0));
        $container.removeClass("is-view-leaving");
        $container.addClass("is-view-entering");
        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
                $container.removeClass("is-view-entering");
                window.setTimeout(() => $container.css("min-height", ""), 180);
            });
        });
    };

    $(document).on("click", "[data-content-view-mode]", function (event) {
        event.preventDefault();

        const $button = $(this);
        const mode = String($button.data("contentViewMode") || "grid");
        const $switcher = $button.closest("[data-content-view-switcher]");
        const $root = $switcher.closest("[data-content-view-root]");
        const $container = $root.find("[data-content-view-container]").first();
        const currentMode = String($root.attr("data-content-view-current") || "grid");

        if (!$root.length || !$container.length || mode === currentMode) return;

        if (activeRequest) activeRequest.abort();

        const height = $container.outerHeight();
        if (height) $container.css("min-height", `${height}px`);
        $container.addClass("is-view-leaving");
        window.CappersSkeleton?.loading($container.get(0));
        setButtons($switcher, currentMode, true);

        const request = $.ajax({
            url: requestUrl(mode),
            method: "GET",
            dataType: "html",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
            cache: false,
        });
        activeRequest = request;

        request
            .done((html) => {
                $container.html(html);
                $root.attr("data-content-view-current", mode);
                setButtons($switcher, mode, false);
                persistMode($switcher, mode);
                window.CappersSkeleton?.watchImages($container.get(0));
                finish($container);
                document.dispatchEvent(
                    new CustomEvent("content-view:updated", {
                        detail: { mode, root: $root.get(0), container: $container.get(0) },
                    })
                );
            })
            .fail((_xhr, status) => {
                if (status === "abort") return;
                setButtons($switcher, currentMode, false);
                finish($container);
            })
            .always(() => {
                if (activeRequest === request) activeRequest = null;
            });
    });
})(window.jQuery);
