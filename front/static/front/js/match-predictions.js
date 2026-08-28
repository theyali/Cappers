(() => {
    const detailMain = document.querySelector(".match-detail-page .match-detail-main");
    if (!detailMain || document.querySelector("[data-match-predictions-feed]")) return;

    const endpoint = `${window.location.pathname.replace(/\/$/, "")}/predictions/`;
    const feed = document.createElement("section");
    feed.className = "match-predictions-feed";
    feed.dataset.matchPredictionsFeed = "";
    feed.dataset.url = endpoint;
    feed.setAttribute("aria-label", "Прогнозы на матч");
    feed.innerHTML = `
        <div class="match-predictions-feed-head">
            <div>
                <p class="match-predictions-kicker">Мнения капперов</p>
                <h2>Все прогнозы на игру <span data-match-predictions-total></span></h2>
            </div>
        </div>
        <div class="match-predictions-list" data-match-predictions-list></div>
        <div class="match-predictions-loader" data-match-predictions-loader hidden>
            <span class="match-predictions-dots" aria-hidden="true"><i></i><i></i><i></i></span>
            <span>Загружаем прогнозы...</span>
        </div>
        <div class="match-predictions-sentinel" data-match-predictions-sentinel aria-hidden="true"></div>`;

    const providerPanel = detailMain.querySelector(":scope > .match-provider-predictions");
    if (providerPanel) {
        providerPanel.insertAdjacentElement("afterend", feed);
    } else {
        detailMain.append(feed);
    }

    const list = feed.querySelector("[data-match-predictions-list]");
    const sentinel = feed.querySelector("[data-match-predictions-sentinel]");
    const loader = feed.querySelector("[data-match-predictions-loader]");
    const totalNode = feed.querySelector("[data-match-predictions-total]");

    let nextPage = 1;
    let isLoading = false;
    let finished = false;
    let observer = null;
    let scrollFallbackBound = false;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const showLoader = (show) => {
        loader.hidden = !show;
    };

    const formatPercent = (value) => {
        const number = Number(value || 0);
        if (!Number.isFinite(number)) return "0%";
        const rounded = Math.round(number * 10) / 10;
        return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}%`;
    };

    const distributionKey = (market, selection) => `${String(market || "").trim()}\u0000${String(selection || "").trim()}`;

    const enrichLockedOddsButtons = () => {
        const teamNames = document.querySelectorAll(".match-detail-scoreboard .match-detail-team > strong");
        const homeName = teamNames[0]?.textContent.trim() || "Хозяева";
        const awayName = teamNames[1]?.textContent.trim() || "Гости";
        const mapping = new Map([
            ["1", ["winner", homeName]],
            ["X", ["winner", "Ничья"]],
            ["2", ["winner", awayName]],
            ["ТБ 2.5", ["total", "ТБ 2.5"]],
            ["ТМ 2.5", ["total", "ТМ 2.5"]],
            ["ОЗ Да", ["both_score", "Обе забьют: да"]],
        ]);

        document.querySelectorAll(".match-detail-locked-options .match-bet-option").forEach((button) => {
            const label = button.querySelector(":scope > span")?.textContent.trim();
            const entry = mapping.get(label);
            if (!entry) return;
            button.dataset.market = entry[0];
            button.dataset.selection = entry[1];
        });
    };

    enrichLockedOddsButtons();

    const oddsButtons = () => document.querySelectorAll(
        ".match-detail-page .odds-button[data-market][data-selection], " +
        ".match-detail-page .match-detail-locked-options .match-bet-option[data-market][data-selection]",
    );

    const unwrapOddsButton = (button) => {
        const wrapper = button.parentElement;
        if (!wrapper?.classList.contains("odds-button-percent-wrap")) return;
        wrapper.replaceWith(button);
    };

    const clearPredictionShares = () => {
        oddsButtons().forEach((button) => {
            button.classList.remove("has-prediction-share");
            button.style.removeProperty("--prediction-share");
            button.querySelector(".odds-prediction-fill")?.remove();
            button.querySelector(".odds-prediction-share")?.remove();
            button.removeAttribute("data-prediction-share");
            button.removeAttribute("title");
            unwrapOddsButton(button);
        });
    };

    const ensurePercentWrapper = (button) => {
        let wrapper = button.parentElement;
        if (!wrapper?.classList.contains("odds-button-percent-wrap")) {
            wrapper = document.createElement("div");
            wrapper.className = "odds-button-percent-wrap";
            wrapper.style.display = "grid";
            wrapper.style.gap = "7px";
            wrapper.style.minWidth = "0";
            button.before(wrapper);
            wrapper.append(button);
        }

        let percentNode = wrapper.querySelector(":scope > .odds-prediction-percent");
        if (!percentNode) {
            percentNode = document.createElement("span");
            percentNode.className = "odds-prediction-percent";
            percentNode.style.display = "block";
            percentNode.style.minHeight = "14px";
            percentNode.style.paddingLeft = "2px";
            percentNode.style.color = "var(--green)";
            percentNode.style.fontSize = "11px";
            percentNode.style.fontWeight = "700";
            percentNode.style.lineHeight = "1";
            percentNode.style.letterSpacing = ".02em";
            wrapper.prepend(percentNode);
        }
        return percentNode;
    };

    const renderPredictionShares = (distribution, total) => {
        const totalPredictions = Number(total || 0);
        if (!totalPredictions) {
            clearPredictionShares();
            return;
        }

        const distributionMap = new Map(
            (Array.isArray(distribution) ? distribution : []).map((item) => [
                distributionKey(item.market, item.selection),
                item,
            ]),
        );

        oddsButtons().forEach((button) => {
            const entry = distributionMap.get(distributionKey(button.dataset.market, button.dataset.selection));
            const count = Number(entry?.count || 0);
            const percent = Math.max(0, Math.min(100, Number(entry?.percent || 0)));
            const percentLabel = formatPercent(percent);

            button.classList.remove("has-prediction-share");
            button.style.removeProperty("--prediction-share");
            button.querySelector(".odds-prediction-fill")?.remove();
            button.querySelector(".odds-prediction-share")?.remove();
            button.dataset.predictionShare = String(percent);
            button.title = `${count} из ${totalPredictions} прогнозов — ${percentLabel}`;

            const percentNode = ensurePercentWrapper(button);
            percentNode.textContent = percentLabel;
        });
    };

    const showEmpty = () => {
        if (list.children.length) return;
        list.innerHTML = `
            <div class="match-predictions-empty">
                <strong>Прогнозов пока нет</strong>
                <span>Когда капперы опубликуют прогноз на эту игру, он появится здесь.</span>
            </div>`;
    };

    const showError = (message) => {
        if (list.querySelector(".match-predictions-error")) return;
        const node = document.createElement("div");
        node.className = "match-predictions-error";
        node.innerHTML = `
            <strong>Не удалось загрузить прогнозы</strong>
            <span></span>
            <button type="button">Повторить</button>`;
        node.querySelector("span").textContent = message || "Попробуйте ещё раз.";
        node.querySelector("button").addEventListener("click", () => {
            node.remove();
            if (observer) observer.observe(sentinel);
            loadNextPage();
        });
        list.append(node);
    };

    const appendPredictionHtml = (html) => {
        if (!html || !html.trim()) return [];

        const template = document.createElement("template");
        template.innerHTML = html.trim();
        const existingIds = new Set(
            Array.from(list.querySelectorAll("[data-prediction-card]"))
                .map((node) => node.dataset.predictionCard)
                .filter(Boolean),
        );
        const nodes = Array.from(template.content.children).filter((node) => {
            const id = node.dataset.predictionCard;
            return !id || !existingIds.has(id);
        });

        nodes.forEach((node, index) => {
            list.appendChild(node);
            if (!reducedMotion) {
                node.animate(
                    [
                        { opacity: 0, transform: "translateY(16px)" },
                        { opacity: 1, transform: "translateY(0)" },
                    ],
                    {
                        duration: 300,
                        delay: Math.min(index, 5) * 45,
                        easing: "cubic-bezier(.2,.8,.2,1)",
                        fill: "both",
                    },
                );
            }
        });

        if (nodes.length) {
            document.dispatchEvent(new CustomEvent("match-predictions:appended", {
                detail: { nodes },
            }));
        }
        return nodes;
    };

    const loadNextPage = async () => {
        if (isLoading || finished) return;
        isLoading = true;
        showLoader(true);

        try {
            const response = await fetch(`${endpoint}?page=${nextPage}`, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
                cache: "no-store",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Ошибка загрузки.");
            }

            const total = Number(result.total || 0);
            totalNode.textContent = total ? `(${total})` : "";
            renderPredictionShares(result.distribution, total);
            appendPredictionHtml(result.html || "");

            if (result.has_next && result.next_page) {
                nextPage = Number(result.next_page);
            } else {
                finished = true;
                observer?.disconnect();
                showEmpty();
            }
        } catch (error) {
            observer?.disconnect();
            showError(error.message);
        } finally {
            isLoading = false;
            showLoader(false);
        }
    };

    const maybeLoadFromScroll = () => {
        if (isLoading || finished) return;
        const rect = sentinel.getBoundingClientRect();
        if (rect.top <= window.innerHeight + 360) loadNextPage();
    };

    if ("IntersectionObserver" in window) {
        observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) loadNextPage();
        }, { rootMargin: "360px 0px", threshold: 0.01 });
        observer.observe(sentinel);
    } else if (!scrollFallbackBound) {
        scrollFallbackBound = true;
        let ticking = false;
        const onScroll = () => {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(() => {
                ticking = false;
                maybeLoadFromScroll();
            });
        };
        window.addEventListener("scroll", onScroll, { passive: true });
        window.addEventListener("resize", onScroll);
    }

    loadNextPage();
})();
