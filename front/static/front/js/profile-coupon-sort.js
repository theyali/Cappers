(() => {
    const desktopLists = Array.from(document.querySelectorAll("[data-profile-coupon-sort-list]"));
    const controls = document.querySelector("[data-profile-coupon-sort-controls]");
    const mobileFeed = document.querySelector("[data-profile-mobile-coupons]");
    if ((!desktopLists.length && !mobileFeed) || !controls) return;

    const loadJQuery = () => {
        if (window.jQuery) return Promise.resolve(window.jQuery);

        return new Promise((resolve, reject) => {
            let script = document.querySelector("script[data-profile-jquery]");
            if (!script) {
                script = document.createElement("script");
                script.src = "https://code.jquery.com/jquery-3.7.1.min.js";
                script.dataset.profileJquery = "true";
                script.async = true;
                document.head.appendChild(script);
            }

            const finish = () => {
                if (window.jQuery) resolve(window.jQuery);
                else reject(new Error("jQuery не загрузился."));
            };

            if (window.jQuery) {
                finish();
                return;
            }

            script.addEventListener("load", finish, { once: true });
            script.addEventListener(
                "error",
                () => reject(new Error("Не удалось загрузить jQuery.")),
                { once: true },
            );
        });
    };

    const parseNumber = (value) => {
        const normalized = String(value ?? "0")
            .replace(/\s+/g, "")
            .replace(",", ".")
            .replace(/[^0-9.-]/g, "");
        const number = Number.parseFloat(normalized);
        return Number.isFinite(number) ? number : 0;
    };

    loadJQuery()
        .then(($) => {
            const $controls = $(controls);
            const $buttons = $controls.find("[data-profile-coupon-sort]");
            const mobileList = mobileFeed?.querySelector("[data-profile-mobile-coupons-list]");
            const moreButton = mobileFeed?.querySelector("[data-profile-mobile-coupons-more]");
            const $mobileFeed = mobileFeed ? $(mobileFeed) : null;
            let activeKey = "date";
            let direction = "desc";
            let isLoading = false;

            const getSortData = (item) => {
                const dataNode = item.querySelector("[data-profile-coupon-sort-data]");
                return dataNode ? dataNode.dataset : {};
            };

            const getDesktopItems = (list) => (
                $(list).children(".profile-coupon-row, .profile-coupon-card").get()
            );

            const updateControls = () => {
                $buttons.each(function () {
                    const $button = $(this);
                    const key = String($button.data("profile-coupon-sort") || "");
                    const isActive = key === activeKey;
                    $button.toggleClass("is-active", isActive);
                    $button.attr("aria-pressed", isActive ? "true" : "false");

                    const $arrow = $button.find("[data-sort-arrow]");
                    if ($arrow.length) {
                        $arrow.text(isActive ? (direction === "asc" ? "↑" : "↓") : "");
                    }
                });
            };

            const sortDesktopRows = () => {
                desktopLists.forEach((list) => {
                    const $list = $(list);
                    const items = getDesktopItems(list);
                    items.sort((left, right) => {
                        const leftData = getSortData(left);
                        const rightData = getSortData(right);
                        const dataKey = `sort${activeKey.charAt(0).toUpperCase()}${activeKey.slice(1)}`;
                        const leftValue = parseNumber(leftData[dataKey]);
                        const rightValue = parseNumber(rightData[dataKey]);

                        if (leftValue === rightValue) {
                            const leftId = parseNumber(leftData.couponId);
                            const rightId = parseNumber(rightData.couponId);
                            return direction === "asc" ? leftId - rightId : rightId - leftId;
                        }

                        return direction === "asc"
                            ? leftValue - rightValue
                            : rightValue - leftValue;
                    });

                    items.forEach((item) => $list.append(item));
                });
            };

            const setMobileLoading = (loading) => {
                isLoading = loading;
                if (mobileFeed) mobileFeed.classList.toggle("is-loading", loading);
                if (moreButton) moreButton.disabled = loading;
            };

            const renderMobileCoupons = (payload, append) => {
                if (!mobileList || !payload || !payload.ok) return;

                const $nodes = $(payload.html || "").hide();
                if (append) {
                    $(mobileList).append($nodes);
                    $nodes.slideDown(180);
                } else {
                    $(mobileList).empty().append($nodes);
                    $nodes.fadeIn(160);
                }

                if (moreButton) {
                    moreButton.dataset.nextOffset = String(payload.next_offset || 0);
                    moreButton.hidden = !payload.has_more;
                }
            };

            const loadMobileCoupons = ({ append = false, offset = 0 } = {}) => {
                if (!$mobileFeed || !mobileList || isLoading) {
                    return $.Deferred().resolve().promise();
                }

                setMobileLoading(true);
                return $.ajax({
                    url: String($mobileFeed.data("url") || ""),
                    method: "GET",
                    dataType: "json",
                    data: {
                        sort: activeKey,
                        direction,
                        offset,
                    },
                })
                    .done((payload) => renderMobileCoupons(payload, append))
                    .always(() => setMobileLoading(false));
            };

            $buttons.on("click", function () {
                const key = String($(this).data("profile-coupon-sort") || "");
                if (!key) return;

                if (key === activeKey) {
                    direction = direction === "desc" ? "asc" : "desc";
                } else {
                    activeKey = key;
                    direction = "desc";
                }

                sortDesktopRows();
                updateControls();
                loadMobileCoupons({ append: false, offset: 0 });
            });

            if (moreButton) {
                moreButton.addEventListener("click", () => {
                    loadMobileCoupons({
                        append: true,
                        offset: parseNumber(moreButton.dataset.nextOffset),
                    });
                });
            }

            updateControls();
        })
        .catch((error) => console.error(error));
})();
