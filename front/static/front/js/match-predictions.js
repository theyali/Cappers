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
