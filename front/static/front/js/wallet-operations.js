(function ($) {
    "use strict";

    if (!$) {
        return;
    }

    function initWalletHistory() {
        var $root = $("[data-wallet-history]");
        if (!$root.length) {
            return;
        }

        var $list = $root.find("[data-wallet-history-list]");
        var $loader = $root.find("[data-wallet-history-loader]");
        var $end = $root.find("[data-wallet-history-end]");
        var $sentinel = $root.find("[data-wallet-history-sentinel]");
        var url = $root.attr("data-history-url");
        var nextCursor = $root.attr("data-next-cursor") || "";
        var isLoading = false;

        function setLoading(value) {
            isLoading = value;
            $loader.prop("hidden", !value);
            $root.attr("aria-busy", value ? "true" : "false");
        }

        function showEndIfNeeded() {
            if (!nextCursor && $list.children(".wallet-history-row").length) {
                $end.prop("hidden", false);
            }
        }

        function loadMore() {
            if (isLoading || !nextCursor || !url) {
                return;
            }

            setLoading(true);

            $.ajax({
                url: url,
                method: "GET",
                dataType: "json",
                data: { cursor: nextCursor },
                headers: { "X-Requested-With": "XMLHttpRequest" }
            })
                .done(function (response) {
                    if (!response || !response.ok) {
                        return;
                    }

                    if (response.html) {
                        $list.append(response.html);
                    }

                    nextCursor = response.next_cursor || "";
                    $root.attr("data-next-cursor", nextCursor);
                    showEndIfNeeded();
                })
                .always(function () {
                    setLoading(false);
                });
        }

        function sentinelIsClose() {
            if (!$sentinel.length || !nextCursor) {
                return false;
            }

            var sentinelTop = $sentinel[0].getBoundingClientRect().top;
            return sentinelTop < window.innerHeight + 260;
        }

        if ("IntersectionObserver" in window && $sentinel.length) {
            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        loadMore();
                    }
                });
            }, { rootMargin: "260px 0px" });

            observer.observe($sentinel[0]);
        }

        $(window).on("scroll.walletHistory resize.walletHistory", function () {
            if (sentinelIsClose()) {
                loadMore();
            }
        });

        showEndIfNeeded();
        if (sentinelIsClose()) {
            loadMore();
        }
    }

    $(initWalletHistory);
})(window.jQuery);
