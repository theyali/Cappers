(($) => {
    if (!$) return;

    $(() => {
        const $select = $("[data-cappers-roi-select]");
        const $shell = $("[data-cappers-roi-grid]");
        const $grid = $shell.find(".cappers-pro-grid");
        const $meta = $("[data-cappers-roi-meta]");

        if (!$select.length || !$shell.length || !$grid.length) return;

        let activeRequest = null;
        let currentPeriod = String($select.val() || "30");
        let sequence = 0;

        const finishLoading = () => {
            window.CappersSkeleton?.ready($shell.get(0));
            $shell.removeClass("is-filtering");
            $select.closest(".cappers-roi-period-select").removeClass("is-loading");
            $select.prop("disabled", false);
            window.setTimeout(() => $shell.css("min-height", ""), 220);
        };

        const syncUrl = (period) => {
            if (!window.history?.replaceState) return;
            const url = new URL(window.location.href);
            if (period === "30") {
                url.searchParams.delete("roi_period");
            } else {
                url.searchParams.set("roi_period", period);
            }
            window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
        };

        $select.on("change", function () {
            const period = String($(this).val() || "30");
            if (period === currentPeriod && !activeRequest) return;

            sequence += 1;
            const requestSequence = sequence;

            if (activeRequest) {
                activeRequest.abort();
                activeRequest = null;
            }

            const height = $shell.outerHeight();
            if (height) $shell.css("min-height", `${height}px`);

            $shell.addClass("is-filtering");
            $select.closest(".cappers-roi-period-select").addClass("is-loading");
            $select.prop("disabled", true);
            window.CappersSkeleton?.loading($shell.get(0));

            activeRequest = $.ajax({
                url: $select.data("url") || window.location.pathname,
                method: "GET",
                dataType: "json",
                data: { roi_period: period },
                cache: false,
            })
                .done((response) => {
                    if (requestSequence !== sequence) return;
                    if (!response?.ok) throw new Error("Не удалось обновить рейтинг капперов.");

                    $grid.html(response.html || "");
                    $meta.text(`${response.label} · ${response.experts_count} профилей`);
                    currentPeriod = String(response.period || period);
                    $select.val(currentPeriod);
                    syncUrl(currentPeriod);
                    window.CappersSkeleton?.watchImages($grid.get(0));

                    window.requestAnimationFrame(() => {
                        if (requestSequence === sequence) finishLoading();
                    });
                })
                .fail((_xhr, status) => {
                    if (status === "abort" || requestSequence !== sequence) return;
                    $select.val(currentPeriod);
                    finishLoading();
                })
                .always(() => {
                    if (requestSequence === sequence) activeRequest = null;
                });
        });
    });
})(window.jQuery);
