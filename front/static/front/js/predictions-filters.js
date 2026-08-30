(($) => {
    "use strict";

    if (!$) return;

    let activeRequest = null;
    let filterTimer = null;

    const currentLayout = () => $("[data-predictions-layout]").first();

    const getCookie = (name) => {
        const cookies = document.cookie ? document.cookie.split(";") : [];
        for (const cookie of cookies) {
            const trimmed = cookie.trim();
            if (trimmed.startsWith(`${name}=`)) {
                return decodeURIComponent(trimmed.slice(name.length + 1));
            }
        }
        return "";
    };

    const persistSidebarCollapsed = (collapsed) => {
        const $layout = currentLayout();
        const url = $layout.data("filterStateUrl");
        if (!url || typeof window.fetch !== "function") return;

        const body = new URLSearchParams();
        body.set("collapsed", collapsed ? "1" : "0");

        window.fetch(url, {
            method: "POST",
            credentials: "same-origin",
            keepalive: true,
            headers: {
                "X-CSRFToken": getCookie("csrftoken"),
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            body,
        }).catch(() => {});
    };

    const setSidebarCollapsed = (collapsed, options = {}) => {
        const $layout = currentLayout();
        if (!$layout.length) return;

        $layout.toggleClass("is-filter-collapsed", collapsed);
        const $toggle = $layout.find("[data-prediction-filter-toggle]").first();
        $toggle.attr("aria-expanded", collapsed ? "false" : "true");

        if (options.persist !== false) {
            persistSidebarCollapsed(collapsed);
        }
    };

    const responseDocument = (html) => {
        const nodes = $.parseHTML(html, document, true);
        return $("<div>").append(nodes);
    };

    const syncHero = ($response) => {
        const value = $response.find("[data-predictions-total-value]").first().text();
        if (value !== "") {
            $("[data-predictions-total-value]").first().text(value);
        }

        const heading = $response.find("[data-predictions-heading]").first().text();
        if (heading !== "") {
            $("[data-predictions-heading]").first().text(heading);
        }

        const intro = $response.find("[data-predictions-intro]").first().text();
        if (intro !== "") {
            $("[data-predictions-intro]").first().text(intro);
        }
    };

    const syncDocumentHead = (html) => {
        const parsed = new DOMParser().parseFromString(html, "text/html");
        if (parsed.title) document.title = parsed.title;

        ["description", "robots"].forEach((name) => {
            const next = parsed.querySelector(`meta[name='${name}']`);
            let current = document.querySelector(`meta[name='${name}']`);
            if (!next) return;
            if (!current) {
                current = document.createElement("meta");
                current.setAttribute("name", name);
                document.head.appendChild(current);
            }
            current.setAttribute("content", next.getAttribute("content") || "");
        });

        const nextCanonical = parsed.querySelector("link[rel='canonical']");
        let currentCanonical = document.querySelector("link[rel='canonical']");
        if (nextCanonical) {
            if (!currentCanonical) {
                currentCanonical = document.createElement("link");
                currentCanonical.setAttribute("rel", "canonical");
                document.head.appendChild(currentCanonical);
            }
            currentCanonical.setAttribute("href", nextCanonical.getAttribute("href") || "");
        }
    };

    const animateIncomingResults = () => {
        const $content = currentLayout().find("[data-predictions-content]").first();
        if (!$content.length) return;

        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
                $content.removeClass("is-results-entering");
            });
        });
    };

    const loadPredictions = (url, options = {}) => {
        const $layout = currentLayout();
        if (!$layout.length) {
            window.location.assign(url);
            return;
        }

        const wasCollapsed = $layout.hasClass("is-filter-collapsed");
        const $content = $layout.find("[data-predictions-content]").first();
        const $sort = $layout.find("[data-prediction-sort]").first();

        $layout.addClass("is-loading");
        $content.addClass("is-results-leaving");

        if (options.sortChange) {
            $sort.addClass("is-changing").prop("disabled", true);
        }

        if (activeRequest) activeRequest.abort();

        const request = $.ajax({
            url,
            method: "GET",
            dataType: "html",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        });
        activeRequest = request;

        request
            .done((html) => {
                const $response = responseDocument(html);
                const $nextLayout = $response.find("[data-predictions-layout]").first();

                if (!$nextLayout.length) {
                    window.location.assign(url);
                    return;
                }

                $nextLayout.find("[data-predictions-content]").first().addClass("is-results-entering");
                $layout.replaceWith($nextLayout);
                syncHero($response);
                syncDocumentHead(html);
                setSidebarCollapsed(wasCollapsed, { persist: false });
                animateIncomingResults();

                if (options.pushState !== false) {
                    window.history.pushState({}, "", url);
                }

                document.dispatchEvent(new CustomEvent("predictions:updated"));
                initPredictionsLazy($nextLayout.get(0));
            })
            .fail((xhr, status) => {
                if (status !== "abort") window.location.assign(url);
            })
            .always(() => {
                if (activeRequest === request) activeRequest = null;
                currentLayout().removeClass("is-loading");
            });
    };

    const formUrl = ($form) => {
        const params = new URLSearchParams($form.serialize());
        params.delete("page");

        let action = $form.attr("action") || window.location.pathname;
        const $sport = $form.find("[name='sport']").first();
        if ($sport.length) {
            const selectedUrl = $sport.find("option:selected").data("url");
            action = selectedUrl || $form.data("all-sports-url") || action;
            params.delete("sport");
        }

        if (params.get("sort") === "new") params.delete("sort");
        if (params.get("status") === "all") params.delete("status");

        const query = params.toString();
        return query ? `${action}?${query}` : action;
    };

    const sortUrl = (value) => {
        const url = new URL(window.location.href);
        if (!value || value === "new") url.searchParams.delete("sort");
        else url.searchParams.set("sort", value);
        if (url.searchParams.get("status") === "all") url.searchParams.delete("status");
        url.searchParams.delete("sport");
        url.searchParams.delete("page");
        return url.href;
    };

    const scheduleFormSubmit = ($form, delay) => {
        window.clearTimeout(filterTimer);
        filterTimer = window.setTimeout(() => {
            filterTimer = null;
            $form.trigger("submit");
        }, delay);
    };

    const initPredictionsLazy = (scope = document) => {
        const root = scope.matches?.("[data-predictions-layout]")
            ? scope
            : scope.querySelector?.("[data-predictions-layout]") || document.querySelector("[data-predictions-layout]");
        if (!root) return;
        const sentinel = root.querySelector("[data-predictions-lazy]");
        if (!sentinel || sentinel.dataset.predictionsLazyReady === "true") return;

        sentinel.dataset.predictionsLazyReady = "true";
        const button = sentinel.querySelector("[data-predictions-lazy-button]");
        const status = sentinel.querySelector("[data-predictions-lazy-status]");
        const content = root.querySelector("[data-predictions-content]");
        let nextPage = Number.parseInt(sentinel.dataset.nextPage || "", 10) || null;
        let loading = false;
        let autoEnabled = true;

        const setStatus = (message) => {
            if (status) status.textContent = message;
        };

        const finish = () => {
            nextPage = null;
            sentinel.dataset.nextPage = "";
            sentinel.classList.remove("is-loading");
            sentinel.classList.add("is-done");
            if (button) {
                button.textContent = "Все прогнозы загружены";
                button.setAttribute("disabled", "disabled");
            }
            setStatus("");
        };

        const revive = (page) => {
            nextPage = Number.parseInt(page || "", 10) || null;
            sentinel.dataset.nextPage = nextPage ? String(nextPage) : "";
            sentinel.classList.toggle("is-done", !nextPage);
            if (button) {
                button.toggleAttribute("disabled", !nextPage);
                if (nextPage) button.textContent = "Показать еще";
            }
        };

        const requestUrl = (page) => {
            const url = new URL(window.location.href);
            url.searchParams.set("page", String(page));
            return url.href;
        };

        const appendChildren = (current, next) => {
            if (!current || !next) return [];
            const known = new Set(
                Array.from(current.querySelectorAll("[data-prediction-card]"))
                    .map((node) => node.dataset.predictionCard)
                    .filter(Boolean)
            );
            const added = [];
            Array.from(next.children).forEach((node, index) => {
                const predictionNode = node.matches("[data-prediction-card]")
                    ? node
                    : node.querySelector("[data-prediction-card]");
                const id = predictionNode?.dataset.predictionCard || "";
                if (id && known.has(id)) return;
                if (id) known.add(id);
                node.classList.add("is-lazy-added");
                node.style.animationDelay = `${Math.min(index, 8) * 35}ms`;
                current.appendChild(node);
                added.push(node);
            });
            return added;
        };

        const appendResponse = (html) => {
            const parsed = new DOMParser().parseFromString(html, "text/html");
            const nextLayout = parsed.querySelector("[data-predictions-layout]");
            if (!nextLayout) throw new Error("predictions-lazy-layout-missing");

            const currentTableBody = root.querySelector("[data-predictions-table-body]");
            const nextTableBody = nextLayout.querySelector("[data-predictions-table-body]");
            const added = [
                ...appendChildren(root.querySelector("[data-predictions-grid]"), nextLayout.querySelector("[data-predictions-grid]")),
                ...(currentTableBody && nextTableBody
                    ? appendChildren(currentTableBody, nextTableBody)
                    : appendChildren(root.querySelector(".content-table-view"), nextLayout.querySelector(".content-table-view"))),
            ];

            const nextSentinel = nextLayout.querySelector("[data-predictions-lazy]");
            sentinel.dataset.currentPage = nextSentinel?.dataset.currentPage || sentinel.dataset.nextPage || "";
            if (nextSentinel?.dataset.nextPage) revive(nextSentinel.dataset.nextPage);
            else finish();

            if (added.length) {
                document.dispatchEvent(new CustomEvent("predictions:appended", { detail: { nodes: added } }));
            }
        };

        const loadNext = async () => {
            if (loading || !nextPage) return;
            loading = true;
            sentinel.classList.add("is-loading");
            if (button) {
                button.textContent = "Загружаем...";
                button.setAttribute("disabled", "disabled");
            }
            setStatus("Загружаем следующие прогнозы");

            try {
                const response = await fetch(requestUrl(nextPage), {
                    method: "GET",
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                if (!response.ok) throw new Error("predictions-lazy-request-failed");
                appendResponse(await response.text());
                autoEnabled = true;
            } catch (error) {
                autoEnabled = false;
                setStatus("Не удалось загрузить прогнозы.");
                if (button) button.textContent = "Повторить";
            } finally {
                loading = false;
                sentinel.classList.remove("is-loading");
                if (button && nextPage) button.removeAttribute("disabled");
            }
        };

        button?.addEventListener("click", () => {
            autoEnabled = true;
            loadNext();
        });

        if ("IntersectionObserver" in window) {
            const style = content ? window.getComputedStyle(content) : null;
            const rootNode = style && /(auto|scroll)/.test(style.overflowY) ? content : null;
            const observer = new IntersectionObserver((entries) => {
                if (entries.some((entry) => entry.isIntersecting) && autoEnabled) loadNext();
            }, { root: rootNode, rootMargin: "650px 0px", threshold: 0.01 });
            observer.observe(sentinel);
        }
    };

    $(document).on("click", "[data-prediction-filter-toggle]", (event) => {
        event.preventDefault();
        const $layout = currentLayout();
        setSidebarCollapsed(!$layout.hasClass("is-filter-collapsed"));
    });

    $(document).on("submit", "[data-prediction-filters]", function (event) {
        event.preventDefault();
        loadPredictions(formUrl($(this)));
    });

    $(document).on(
        "change",
        "[data-prediction-filters] select, [data-prediction-filters] input[type='checkbox']",
        function () {
            const $form = $(this).closest("[data-prediction-filters]");
            if (this.name === "sport") $form.find("[name='league']").val("");
            $form.trigger("submit");
        }
    );

    $(document).on(
        "input",
        "[data-prediction-filters] input[type='number'], [data-prediction-filters] input[type='search']",
        function () {
            const $form = $(this).closest("[data-prediction-filters]");
            scheduleFormSubmit($form, this.type === "search" ? 300 : 350);
        }
    );

    $(document).on("change", "[data-prediction-sort]", function () {
        loadPredictions(sortUrl(this.value), { sortChange: true });
    });

    $(document).on(
        "click",
        ".matches-sport-tabs a, .predictions-tabs a, .prediction-filter-reset, [data-prediction-ajax-link]",
        function (event) {
            const href = this.href;
            if (!href) return;

            const target = new URL(href, window.location.href);
            if (target.origin !== window.location.origin) return;

            event.preventDefault();
            loadPredictions(target.href);
        }
    );

    window.addEventListener("popstate", () => {
        loadPredictions(window.location.href, { pushState: false });
    });

    initPredictionsLazy(document);
})(window.jQuery);
