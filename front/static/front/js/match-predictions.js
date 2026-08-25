(() => {
    const feed = document.querySelector("[data-match-predictions-feed]");
    if (!feed) return;

    const list = feed.querySelector("[data-match-predictions-list]");
    const sentinel = feed.querySelector("[data-match-predictions-sentinel]");
    const totalNode = feed.querySelector("[data-match-predictions-total]");
    const loader = feed.querySelector("[data-match-predictions-loader]");
    const endpoint = feed.dataset.url;

    let nextPage = 1;
    let isLoading = false;
    let finished = false;
    let observer = null;

    const showLoader = (show) => {
        if (!loader) return;
        loader.hidden = !show;
    };

    const showEmpty = () => {
        if (!list || list.children.length) return;
        list.innerHTML = `
            <div class="match-predictions-empty">
                <strong>Прогнозов пока нет</strong>
                <span>Когда капперы опубликуют прогноз на эту игру, он появится здесь.</span>
            </div>`;
    };

    const showError = (message) => {
        if (!list) return;
        const node = document.createElement("div");
        node.className = "match-predictions-error";
        node.innerHTML = `
            <strong>Не удалось загрузить прогнозы</strong>
            <span></span>
            <button type="button">Повторить</button>`;
        node.querySelector("span").textContent = message || "Попробуйте ещё раз.";
        node.querySelector("button").addEventListener("click", () => {
            node.remove();
            loadNextPage();
        });
        list.append(node);
    };

    const loadNextPage = async () => {
        if (isLoading || finished || !endpoint) return;
        isLoading = true;
        showLoader(true);

        try {
            const separator = endpoint.includes("?") ? "&" : "?";
            const response = await fetch(`${endpoint}${separator}page=${nextPage}`, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Ошибка загрузки.");
            }

            if (totalNode) totalNode.textContent = result.total;
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

    if ("IntersectionObserver" in window && sentinel) {
        observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) loadNextPage();
        }, { rootMargin: "320px 0px" });
        observer.observe(sentinel);
    } else {
        loadNextPage();
    }
})();
