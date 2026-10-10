(() => {
    document.querySelectorAll("[data-tournament-icon-color]").forEach((icon) => {
        const color = icon.dataset.tournamentIconColor || "";
        if (/^#[0-9a-fA-F]{6}$/.test(color)) {
            icon.style.setProperty("--tournament-icon-color", color);
        }
    });
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
        activateTournamentTab($(this), "home");
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
