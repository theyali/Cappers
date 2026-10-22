(() => {
    const refreshIcons = (root = document) => root.querySelectorAll("[data-tournament-icon-color]").forEach((icon) => {
        const color = icon.dataset.tournamentIconColor || "";
        if (/^#[0-9a-fA-F]{6}$/.test(color)) {
            icon.style.setProperty("--tournament-icon-color", color);
        }
    });
    refreshIcons();
    document.addEventListener("tournament:catalog-updated", (event) => refreshIcons(event.detail.root));
})();

(() => {
    const pad = (value) => String(value).padStart(2, "0");

    const formatRemaining = (milliseconds) => {
        if (milliseconds <= 0) return "";
        const totalSeconds = Math.floor(milliseconds / 1000);
        const days = Math.floor(totalSeconds / 86400);
        const hours = Math.floor((totalSeconds % 86400) / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        if (days > 0) {
            return `${days} д ${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
        }
        return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
    };

    const timers = Array.from(document.querySelectorAll("[data-countdown-target]"))
        .map((node) => ({
            node,
            target: new Date(node.dataset.countdownTarget),
            expired: node.dataset.countdownExpired || "Завершено",
        }))
        .filter((timer) => !Number.isNaN(timer.target.getTime()));

    if (!timers.length) return;

    const tick = () => {
        const now = Date.now();
        timers.forEach((timer) => {
            const remaining = timer.target.getTime() - now;
            timer.node.textContent = remaining > 0 ? formatRemaining(remaining) : timer.expired;
        });
    };

    tick();
    window.setInterval(tick, 1000);
})();

(($) => {
    "use strict";

    if (!$) return;

    const activateTournamentTab = ($root, tab) => {
        const $tabs = $root.find("[data-tournament-tab]");
        const $panels = $root.find("[data-tournament-panel]");
        const $activeTab = $tabs.filter(`[data-tournament-tab="${tab}"]`).first();
        const $activePanel = $panels.filter(`[data-tournament-panel="${tab}"]`).first();

        if (!$activeTab.length || !$activePanel.length) return;

        $tabs
            .removeClass("is-active")
            .attr("aria-selected", "false")
            .attr("tabindex", "-1");
        $activeTab
            .addClass("is-active")
            .attr("aria-selected", "true")
            .attr("tabindex", "0");

        $panels.removeClass("is-active").attr("hidden", true);
        $activePanel.addClass("is-active").removeAttr("hidden");
    };

    $(document).on("click", "[data-tournament-tab]", function handleTournamentTabClick() {
        const $tab = $(this);
        activateTournamentTab($tab.closest("[data-tournament-tabs]"), $tab.data("tournamentTab"));
    });

    $(document).on("click", "[data-tournament-tab-jump]", function handleTournamentTabJump() {
        const $button = $(this);
        activateTournamentTab($button.closest("[data-tournament-tabs]"), $button.data("tournamentTabJump"));
    });

    $(document).on("keydown", "[data-tournament-tab]", function handleTournamentTabKeydown(event) {
        if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;

        const $tabs = $(this).closest("[role='tablist']").find("[data-tournament-tab]");
        const currentIndex = $tabs.index(this);
        let nextIndex = currentIndex;

        if (event.key === "Home") nextIndex = 0;
        if (event.key === "End") nextIndex = $tabs.length - 1;
        if (event.key === "ArrowDown" || event.key === "ArrowRight") nextIndex = (currentIndex + 1) % $tabs.length;
        if (event.key === "ArrowUp" || event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + $tabs.length) % $tabs.length;

        event.preventDefault();
        $tabs.eq(nextIndex).trigger("click").trigger("focus");
    });

    const closeFaqItem = ($item) => {
        const $button = $item.find("[data-tournament-faq-toggle]").first();
        const $panel = $item.find("[data-tournament-faq-panel]").first();
        $item.removeClass("is-open");
        $button.attr("aria-expanded", "false");
        $panel.css("max-height", "0px");
    };

    const openFaqItem = ($item) => {
        const $button = $item.find("[data-tournament-faq-toggle]").first();
        const $panel = $item.find("[data-tournament-faq-panel]").first();
        $item.addClass("is-open");
        $button.attr("aria-expanded", "true");
        $panel.css("max-height", `${$panel.prop("scrollHeight")}px`);
    };

    $(document).on("click", "[data-tournament-faq-toggle]", function handleFaqToggle() {
        const $item = $(this).closest("[data-tournament-faq]");
        const $siblings = $item.siblings("[data-tournament-faq]");
        const shouldOpen = !$item.hasClass("is-open");
        $siblings.each(function closeSiblingFaq() {
            closeFaqItem($(this));
        });
        if (shouldOpen) {
            openFaqItem($item);
        } else {
            closeFaqItem($item);
        }
    });

    $("[data-tournament-tabs]").each(function initializeTournamentTabs() {
        const tab = new URL(window.location.href).searchParams.get("tab");
        activateTournamentTab($(this), ["home", "results", "participants", "prizes", "about"].includes(tab) ? tab : "home");
    });

    let resultsRequest = null;
    let searchTimer = 0;

    const loadTournamentResults = ($scope, options = {}) => {
        const $form = $scope.find("[data-tournament-results-form]").first();
        const url = $form.data("resultsUrl");
        if (!url) return;

        const data = {
            page: options.page || $form.find("[data-results-page]").val() || 1,
            per_page: options.perPage || $form.find("[data-results-per-page]").val() || 10,
            filter: options.filter || $form.find("[data-results-filter].is-active").data("resultsFilter") || "all",
            country: $form.find("[data-results-country]").val() || "all",
            q: $form.find("[data-results-search]").val() || "",
        };

        if (resultsRequest) resultsRequest.abort();
        $scope.addClass("is-loading");
        resultsRequest = $.ajax({
            url,
            method: "GET",
            data,
            dataType: "json",
        }).done((response) => {
            if (!response?.ok || !response.html) return;
            $scope.replaceWith(response.html);
        }).always(() => {
            $scope.removeClass("is-loading");
            resultsRequest = null;
        });
    };

    $(document).on("click", "[data-results-filter]", function handleResultsFilter() {
        const $button = $(this);
        const $scope = $button.closest("[data-tournament-results-content]");
        loadTournamentResults($scope, {
            page: 1,
            filter: $button.data("resultsFilter") || "all",
        });
    });

    $(document).on("click", "[data-results-page-link]", function handleResultsPage() {
        const $button = $(this);
        if ($button.is(":disabled")) return;
        loadTournamentResults($button.closest("[data-tournament-results-content]"), {
            page: $button.data("resultsPageLink") || 1,
        });
    });

    $(document).on("change", "[data-results-per-page], [data-results-country]", function handleResultsSelect() {
        loadTournamentResults($(this).closest("[data-tournament-results-content]"), { page: 1 });
    });

    $(document).on("input", "[data-results-search]", function handleResultsSearch() {
        const $input = $(this);
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => {
            loadTournamentResults($input.closest("[data-tournament-results-content]"), { page: 1 });
        }, 260);
    });

    $(document).on("submit", "[data-tournament-results-form]", function handleResultsSubmit(event) {
        event.preventDefault();
        loadTournamentResults($(this).closest("[data-tournament-results-content]"), { page: 1 });
    });
})(window.jQuery);

(($) => {
    "use strict";
    if (!$) return;
    const $catalog = $("[data-tournament-catalog]").first();
    if (!$catalog.length) return;
    const catalogPath = window.location.pathname;
    let activeRequest = null;
    let sequence = 0;
    let retryUrl = window.location.href;
    let resultsAnimation = null;

    const loadCatalog = (href, { push = true } = {}) => {
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin || url.pathname !== catalogPath) return;
        const requestId = ++sequence;
        if (activeRequest) activeRequest.abort();
        resultsAnimation?.cancel();
        resultsAnimation = null;
        retryUrl = url.href;
        const focused = $catalog[0].contains(document.activeElement) ? document.activeElement : null;
        const focusedSort = focused?.matches("[data-tournament-sort-link]");
        const focusedHref = focused?.closest("a")?.href;
        $catalog.attr("aria-busy", "true");
        $catalog.find("[data-tournament-catalog-error]").prop("hidden", true);
        activeRequest = $.ajax({
            url: url.href,
            method: "GET",
            dataType: "json",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        }).done((result) => {
            if (requestId !== sequence) return;
            if (!result?.ok || typeof result.html !== "string") {
                showError();
                return;
            }
            $catalog.empty().append($.parseHTML(result.html, document, false));
            if (push && url.href !== window.location.href) {
                window.history.pushState({ ...window.history.state, tournamentCatalog: true }, "", url.href);
            }
            window.CappersSkeleton?.watchImages($catalog[0]);
            document.dispatchEvent(new CustomEvent("tournament:catalog-updated", { detail: { root: $catalog[0] } }));
            const focusTarget = focusedSort ? $catalog.find("[data-tournament-sort-link]")[0]
                : focusedHref ? Array.from($catalog[0].querySelectorAll("a")).find((link) => link.href === focusedHref) : null;
            focusTarget?.focus({ preventScroll: true });
            if (!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
                resultsAnimation = $catalog.find("[data-tournament-catalog-results]")[0]?.animate?.(
                    [{ opacity: 0.6 }, { opacity: 1 }],
                    { duration: 240, easing: "ease-out" },
                );
            }
        }).fail((_xhr, status) => {
            if (requestId === sequence && status !== "abort") showError();
        }).always(() => {
            if (requestId !== sequence) return;
            activeRequest = null;
            $catalog.attr("aria-busy", "false");
        });
    };
    const showError = () => {
        $catalog.find("[data-tournament-catalog-error]").prop("hidden", false);
    };
    $(document).on("click", "[data-tournament-filter-link]", function (event) {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || (event.which && event.which !== 1)) return;
        if (this.target && this.target !== "_self") return;
        event.preventDefault();
        loadCatalog(this.href);
    });
    $(document).on("click", "[data-tournament-catalog-retry]", () => loadCatalog(retryUrl));
    window.addEventListener("popstate", () => loadCatalog(window.location.href, { push: false }));
})(window.jQuery);

(() => {
    const modal = document.getElementById("tournament-rules-modal");
    if (!modal) return;
    const panel = modal.querySelector("[data-tournament-rules-panel]");
    let trigger = null;
    let closing = false;
    let animations = [];
    const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const cancelAnimations = () => {
        animations.forEach((animation) => animation.cancel());
        animations = [];
    };
    const play = (opening) => {
        cancelAnimations();
        if (reducedMotion() || typeof panel.animate !== "function") return [];
        animations = [
            modal.animate([{ opacity: opening ? 0 : 1 }, { opacity: opening ? 1 : 0 }],
                { duration: opening ? 240 : 180, easing: "ease-out", fill: "both" }),
            panel.animate([
                { transform: opening ? "translateY(24px)" : "translateY(0)" },
                { transform: opening ? "translateY(0)" : "translateY(24px)" },
            ], { duration: opening ? 280 : 180, easing: "cubic-bezier(.2,.8,.2,1)", fill: "both" }),
        ];
        return animations;
    };
    const close = async () => {
        if (!modal.open || closing) return;
        closing = true;
        await Promise.allSettled(play(false).map((animation) => animation.finished));
        modal.close();
    };
    document.addEventListener("click", (event) => {
        const opener = event.target.closest("[data-tournament-rules-open]");
        if (!opener) return;
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        if (modal.open) return;
        trigger = opener;
        closing = false;
        modal.showModal();
        document.documentElement.classList.add("has-tournament-rules-modal");
        play(true);
        modal.querySelector("[data-tournament-rules-close]")?.focus({ preventScroll: true });
    });
    modal.addEventListener("click", (event) => {
        if (event.target === modal || event.target.closest("[data-tournament-rules-close]")) close();
    });
    modal.addEventListener("cancel", (event) => {
        event.preventDefault();
        close();
    });
    modal.addEventListener("close", () => {
        cancelAnimations();
        closing = false;
        document.documentElement.classList.remove("has-tournament-rules-modal");
        (trigger?.isConnected ? trigger : document.querySelector("[data-tournament-rules-open]"))?.focus({ preventScroll: true });
    });
})();

(($) => {
    if (!$ || !document.querySelector("[data-tournament-participants]")) return;
    let request = null;
    let sequence = 0;
    let searchTimer = 0;
    let retry = null;
    const load = (href, { append = false, searchFocus = false } = {}) => {
        const $scope = $("[data-tournament-participants]").first();
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin || url.pathname !== window.location.pathname) return;
        clearTimeout(searchTimer);
        const id = ++sequence;
        request?.abort();
        retry = () => load(href, { append, searchFocus });
        $scope.attr("aria-busy", "true");
        $scope.find("[data-participants-error]").prop("hidden", true);
        const input = $scope.find("[data-participants-search]")[0];
        const queryAtStart = input?.value;
        const focused = $scope[0].contains(document.activeElement);
        request = $.ajax({ url: $scope.data("participantsEndpoint") + url.search, method: "GET", dataType: "json",
            headers: { "X-Requested-With": "XMLHttpRequest" } })
            .done((result) => {
                if (id !== sequence) return;
                if (!result?.ok || typeof result.html !== "string") {
                    $scope.find("[data-participants-error]").prop("hidden", false);
                    return;
                }
                const $new = $($.parseHTML(result.html, document, false)).filter("[data-tournament-participants]");
                if (!$new.length) {
                    $scope.find("[data-participants-error]").prop("hidden", false);
                    return;
                }
                // Preserve any newer search text entered while this response was in flight.
                if (input && input.value !== queryAtStart) return;
                if (append) {
                    const existing = $scope.find("[data-participants-rows]").children().detach();
                    $new.find("[data-participants-rows]").prepend(existing);
                }
                $scope.replaceWith($new);
                if (focused && searchFocus) $new.find("[data-participants-search]")[0]?.focus({ preventScroll: true });
                else if (focused) $new.find(append ? "[data-participants-more]" : ".tournament-participants-sort")[0]?.focus({ preventScroll: true });
                if (!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
                    $new.find(".tournament-participants-list")[0]?.animate?.([{ opacity: .6 }, { opacity: 1 }], { duration: 240, easing: "ease-out" });
                }
            }).fail((_xhr, status) => {
                if (id === sequence && status !== "abort") $scope.find("[data-participants-error]").prop("hidden", false);
            }).always(() => {
                if (id !== sequence) return;
                request = null;
                $scope.attr("aria-busy", "false");
            });
    };
    $(document).on("click", "[data-participants-link], [data-participants-more]", function (event) {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || (event.which && event.which !== 1)) return;
        event.preventDefault();
        load(this.href, { append: this.hasAttribute("data-participants-more") });
    });
    const search = (form) => {
        const url = new URL(form.action, window.location.href);
        url.search = $(form).serialize();
        load(url.href, { searchFocus: true });
    };
    $(document).on("input", "[data-participants-search]", function () {
        clearTimeout(searchTimer);
        const form = this.form;
        searchTimer = setTimeout(() => search(form), 300);
    });
    $(document).on("submit", "[data-participants-search-form]", function (event) {
        event.preventDefault();
        search(this);
    });
    $(document).on("click", "[data-participants-retry]", () => retry?.());
})(window.jQuery);
