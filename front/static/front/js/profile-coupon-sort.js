(() => {
    const list = document.querySelector("[data-profile-coupon-sort-list]");
    const controls = document.querySelector("[data-profile-coupon-sort-controls]");
    if (!list || !controls) return;

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
            const $list = $(list);
            const $controls = $(controls);
            const $buttons = $controls.find("[data-profile-coupon-sort]");
            let activeKey = "date";
            let direction = "desc";

            const getSortData = (item) => {
                const dataNode = item.querySelector("[data-profile-coupon-sort-data]");
                return dataNode ? dataNode.dataset : {};
            };

            const getItems = () => $list
                .children(".profile-coupon-row, .profile-coupon-card")
                .get();

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

            const sortRows = () => {
                const items = getItems();
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
                updateControls();
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

                sortRows();
            });

            updateControls();
        })
        .catch((error) => console.error(error));
})();
