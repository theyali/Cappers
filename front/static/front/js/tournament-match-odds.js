(($) => {
    "use strict";

    if (!$) return;

    const $page = $(".tournament-predict-page");
    if (!$page.length) return;

    const closeRow = ($row, $panelRow) => {
        $row.removeClass("is-expanded").attr("aria-expanded", "false");
        $panelRow.stop(true, true).slideUp(180, () => {
            $panelRow.attr("hidden", true);
        });
    };

    const openRow = ($row, $panelRow) => {
        $row.addClass("is-expanded").attr("aria-expanded", "true");
        $panelRow.removeAttr("hidden").hide().stop(true, true).slideDown(220);
    };

    const renderError = ($panel, message) => {
        $panel.html(
            `<div class="tournament-match-odds-error">${message || "Не удалось загрузить коэффициенты."}</div>`
        );
    };

    const loadOdds = ($row, $panelRow) => {
        const $panel = $panelRow.find("[data-tournament-match-odds-panel]").first();
        if ($panelRow.data("loaded") === true || $panelRow.data("loading") === true) return;

        const url = $row.data("tournamentMatchOddsUrl");
        if (!url) {
            renderError($panel);
            return;
        }

        $panelRow.data("loading", true);
        $panel.html('<div class="tournament-match-odds-loading">Загружаем коэффициенты...</div>');

        $.ajax({
            url,
            method: "GET",
            dataType: "json",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        }).done((payload) => {
            if (!payload || payload.ok !== true) {
                renderError($panel, payload?.error);
                return;
            }
            $panel.html(payload.html || "");
            $panelRow.data("loaded", true);
            document.dispatchEvent(new CustomEvent("matches:appended", { detail: { nodes: [$panelRow.get(0)] } }));
        }).fail((xhr) => {
            renderError($panel, xhr.responseJSON?.error);
        }).always(() => {
            $panelRow.data("loading", false);
        });
    };

    const toggleRow = ($row) => {
        const $panelRow = $row.next("[data-tournament-match-odds-row]");
        if (!$panelRow.length) return;

        if ($row.hasClass("is-expanded")) {
            closeRow($row, $panelRow);
            return;
        }

        loadOdds($row, $panelRow);
        openRow($row, $panelRow);
    };

    $page.on("click", "[data-tournament-match-toggle]", function (event) {
        event.preventDefault();
        event.stopPropagation();
        toggleRow($(this).closest("[data-tournament-match-row]"));
    });

    $page.on("click", "[data-tournament-match-row]", function (event) {
        if ($(event.target).closest("button, a, input, select, textarea, label, [data-bet-option]").length) return;
        toggleRow($(this));
    });

})(window.jQuery);
