(() => {
    const detailMain = document.querySelector(".match-detail-page .match-detail-main");
    if (!detailMain) return;

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
                <h2>Все прогнозы на игру</h2>
            </div>
        </div>
        <div class="match-predictions-list" data-match-predictions-list></div>
        <div class="match-predictions-loader" data-match-predictions-loader hidden>
            <span class="match-predictions-dots" aria-hidden="true"><i></i><i></i><i></i></span>
            <span>Загружаем прогнозы...</span>
        </div>
        <div class="match-predictions-sentinel" data-match-predictions-sentinel aria-hidden="true"></div>`;
    detailMain.append(feed);

    const list = feed.querySelector("[data-match-predictions-list]");
    const sentinel = feed.querySelector("[data-match-predictions-sentinel]");
    const loader = feed.querySelector("[data-match-predictions-loader]");

    let nextPage = 1;
    let isLoading = false;
    let finished = false;
    let observer = null;

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

    const clearPredictionShares = () => {
        document.querySelectorAll(".match-detail-page .odds-button.has-prediction-share").forEach((button) => {
            button.classList.remove("has-prediction-share");
            button.style.removeProperty("--prediction-share");
            button.querySelector(".odds-prediction-fill")?.remove();
            button.querySelector(".odds-prediction-share")?.remove();
            button.removeAttribute("data-prediction-share");
            button.removeAttribute("title");
        });
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

        document.querySelectorAll(".match-detail-page .odds-button[data-market][data-selection]").forEach((button) => {
            const entry = distributionMap.get(distributionKey(button.dataset.market, button.dataset.selection));
            const count = Number(entry?.count || 0);
            const percent = Math.max(0, Math.min(100, Number(entry?.percent || 0)));
            const percentLabel = formatPercent(percent);

            let fill = button.querySelector(".odds-prediction-fill");
            if (!fill) {
                fill = document.createElement("i");
                fill.className = "odds-prediction-fill";
                fill.setAttribute("aria-hidden", "true");
                button.prepend(fill);
            }

            let share = button.querySelector(".odds-prediction-share");
            if (!share) {
                share = document.createElement("em");
                share.className = "odds-prediction-share";
                button.append(share);
            }

            button.classList.add("has-prediction-share");
            button.style.setProperty("--prediction-share", `${percent}%`);
            button.dataset.predictionShare = String(percent);
            button.title = `${count} из ${totalPredictions} прогнозов — ${percentLabel}`;
            share.textContent = `${percentLabel} прогнозов`;
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

    const loadNextPage = async () => {
        if (isLoading || finished) return;
        isLoading = true;
        showLoader(true);

        try {
            const response = await fetch(`${endpoint}?page=${nextPage}`, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Ошибка загрузки.");
            }

            renderPredictionShares(result.distribution, result.total);
            if (result.html) list.insertAdjacentHTML("beforeend", result.html);

            if (result.has_next) {
                nextPage = result.next_page;
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

    if ("IntersectionObserver" in window) {
        observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) loadNextPage();
        }, { rootMargin: "320px 0px" });
        observer.observe(sentinel);
    } else {
        loadNextPage();
    }
})();
