(($) => {
    "use strict";

    if (!$) return;

    let persistRequest = null;
    let selectedMode = null;

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

        if (persistRequest) persistRequest.abort();
        const csrfToken = decodeURIComponent(getCookie("csrftoken"));
        const options = csrfToken
            ? {
                url: stateUrl,
                method: "POST",
                dataType: "json",
                data: { mode },
                headers: {
                    "X-CSRFToken": csrfToken,
                    "X-Requested-With": "XMLHttpRequest",
                },
            }
            : {
                url: stateUrl,
                method: "GET",
                dataType: "json",
                data: { mode },
                headers: { "X-Requested-With": "XMLHttpRequest" },
            };

        persistRequest = $.ajax(options).always(() => {
            persistRequest = null;
        });
    };

    const setButtons = ($switcher, mode) => {
        $switcher.find("[data-content-view-mode]").each(function () {
            const $button = $(this);
            const active = String($button.data("contentViewMode")) === mode;
            $button.toggleClass("is-active", active);
            $button.attr("aria-pressed", active ? "true" : "false");
        });
    };

    const dispatchUpdated = ($root, $panel, mode) => {
        document.dispatchEvent(
            new CustomEvent("content-view:updated", {
                detail: { mode, root: $root.get(0), panel: $panel.get(0) },
            })
        );
    };

    const applyMode = ($root, mode, { animate = false } = {}) => {
        if (!$root.length || !["grid", "table"].includes(mode)) return;

        const $panels = $root.find("[data-content-view-panel]");
        const $next = $panels.filter(`[data-content-view-panel='${mode}']`).first();
        if (!$next.length) return;

        const $current = $panels.filter(":not([hidden])").first();
        const $container = $root.find("[data-content-view-container]").first();
        const $switcher = $root.find("[data-content-view-switcher]").first();

        setButtons($switcher, mode);
        $root.attr("data-content-view-current", mode);
        selectedMode = mode;

        if (!animate || !$current.length || $current.is($next)) {
            $panels.attr("hidden", true);
            $next.removeAttr("hidden");
            window.CappersSkeleton?.watchImages($next.get(0));
            dispatchUpdated($root, $next, mode);
            return;
        }

        const height = $current.outerHeight();
        if (height) $container.css("min-height", `${height}px`);
        $container.addClass("is-view-leaving");

        window.setTimeout(() => {
            $current.attr("hidden", true);
            $next.removeAttr("hidden");
            window.CappersSkeleton?.watchImages($next.get(0));

            $container.removeClass("is-view-leaving").addClass("is-view-entering");
            window.requestAnimationFrame(() => {
                window.requestAnimationFrame(() => {
                    $container.removeClass("is-view-entering");
                    window.setTimeout(() => $container.css("min-height", ""), 180);
                });
            });

            dispatchUpdated($root, $next, mode);
        }, 110);
    };

    const syncRenderedRoots = () => {
        $("[data-content-view-root]").each(function () {
            const $root = $(this);
            const mode = selectedMode || String($root.attr("data-content-view-current") || "grid");
            applyMode($root, mode, { animate: false });
        });
    };

    const keepLockedSportsOpen = (scope = document) => {
        scope.querySelectorAll?.(".content-sport-accordion[data-sport-locked='true']").forEach((details) => {
            if (details instanceof HTMLDetailsElement) details.open = true;
        });
    };

    $(() => {
        syncRenderedRoots();
        keepLockedSportsOpen(document);
    });

    $(document).on("click", "[data-content-view-mode]", function (event) {
        event.preventDefault();

        const $button = $(this);
        const mode = String($button.data("contentViewMode") || "grid");
        const $switcher = $button.closest("[data-content-view-switcher]");
        const $root = $switcher.closest("[data-content-view-root]");
        const currentMode = String($root.attr("data-content-view-current") || "grid");

        if (!$root.length || mode === currentMode) return;

        applyMode($root, mode, { animate: true });
        persistMode($switcher, mode);
    });

    $(document).on(
        "click keydown",
        ".content-sport-accordion[data-sport-locked='true'] > .content-sport-summary",
        function (event) {
            if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
            event.preventDefault();
            const details = this.parentElement;
            if (details instanceof HTMLDetailsElement) details.open = true;
        }
    );

    document.addEventListener("toggle", (event) => {
        const details = event.target;
        if (!(details instanceof HTMLDetailsElement)) return;
        if (details.dataset.sportLocked !== "true" || details.open) return;
        details.open = true;
    }, true);

    document.addEventListener("predictions:updated", () => {
        syncRenderedRoots();
        keepLockedSportsOpen(document);
    });

    document.addEventListener("matches:filters-updated", () => {
        syncRenderedRoots();
        keepLockedSportsOpen(document);
    });

    window.CappersContentViewMode = {
        sync: syncRenderedRoots,
        applyMode,
    };

    document.addEventListener("matches:watch-changed", (event) => {
        const matchId = String(event.detail?.matchId || "");
        if (!matchId) return;
        const watching = Boolean(event.detail?.watching);

        document.querySelectorAll(`[data-match-shell-id='${CSS.escape(matchId)}']`).forEach((shell) => {
            shell.classList.toggle("is-watched", watching);
            shell.querySelectorAll("[data-match-watch-toggle]").forEach((button) => {
                button.classList.toggle("is-watching", watching);
                button.setAttribute("aria-pressed", watching ? "true" : "false");
                button.setAttribute("aria-label", watching ? "Не отслеживать матч" : "Отслеживать матч");
                button.title = watching ? "Матч отслеживается" : "Следить за матчем";
            });
        });
    });
})(window.jQuery);
