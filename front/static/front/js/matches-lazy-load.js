(() => {
    const grid = document.querySelector("[data-matches-grid]");
    const sentinel = document.querySelector("[data-matches-lazy]");
    if (!grid || !sentinel || sentinel.classList.contains("is-done")) return;

    const button = sentinel.querySelector("[data-matches-lazy-button]");
    const status = sentinel.querySelector("[data-matches-lazy-status]");
    let nextPage = Number.parseInt(sentinel.dataset.nextPage || "", 10);
    let loading = false;
    let autoEnabled = true;
    let observer = null;

    const setStatus = (message) => {
        if (status) status.textContent = message;
    };

    const finish = () => {
        nextPage = null;
        sentinel.dataset.nextPage = "";
        sentinel.classList.remove("is-loading");
        sentinel.classList.add("is-done");
        observer?.disconnect();
    };

    const requestUrl = (page) => {
        const url = new URL(window.location.href);
        url.searchParams.set("page", String(page));
        return `${url.pathname}?${url.searchParams.toString()}`;
    };

    const appendHtml = (html) => {
        if (!html || !html.trim()) return [];

        const template = document.createElement("template");
        template.innerHTML = html.trim();
        const existingIds = new Set(
            Array.from(grid.querySelectorAll("[data-match-shell-id]"))
                .map((node) => node.dataset.matchShellId)
                .filter(Boolean)
        );
        const nodes = Array.from(template.content.children).filter((node) => {
            const id = node.dataset.matchShellId;
            return !id || !existingIds.has(id);
        });

        nodes.forEach((node, index) => {
            node.classList.add("is-lazy-added");
            node.style.animationDelay = `${Math.min(index, 8) * 35}ms`;
            grid.appendChild(node);
        });

        if (nodes.length) {
            document.dispatchEvent(new CustomEvent("matches:appended", {
                detail: { nodes },
            }));
        }
        return nodes;
    };

    const maybeContinue = () => {
        if (!autoEnabled || loading || !nextPage) return;
        const rect = sentinel.getBoundingClientRect();
        if (rect.top <= window.innerHeight + 650) {
            window.setTimeout(loadNext, 90);
        }
    };

    const loadNext = async () => {
        if (loading || !nextPage) return;
        loading = true;
        sentinel.classList.add("is-loading");
        button?.setAttribute("disabled", "disabled");
        if (button) button.textContent = "Загружаем...";
        setStatus("Загружаем следующие матчи");

        const requestedPage = nextPage;
        try {
            const response = await fetch(requestUrl(requestedPage), {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            if (!response.ok) throw new Error("lazy-load-request-failed");

            const payload = await response.json();
            if (!payload?.ok) throw new Error("lazy-load-response-invalid");

            appendHtml(payload.html || "");
            sentinel.dataset.currentPage = String(payload.page || requestedPage);

            if (payload.has_next && payload.next_page) {
                nextPage = Number.parseInt(payload.next_page, 10);
                sentinel.dataset.nextPage = String(nextPage);
                setStatus("");
            } else {
                finish();
            }
        } catch (error) {
            autoEnabled = false;
            setStatus("Не удалось загрузить матчи.");
            if (button) button.textContent = "Повторить";
        } finally {
            loading = false;
            sentinel.classList.remove("is-loading");
            if (button && nextPage) {
                button.removeAttribute("disabled");
                if (autoEnabled) button.textContent = "Показать ещё";
            }
            maybeContinue();
        }
    };

    button?.addEventListener("click", () => {
        autoEnabled = true;
        loadNext();
    });

    if ("IntersectionObserver" in window) {
        observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting) && autoEnabled) {
                loadNext();
            }
        }, {
            root: null,
            rootMargin: "650px 0px",
            threshold: 0.01,
        });
        observer.observe(sentinel);
    } else {
        let ticking = false;
        const onScroll = () => {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(() => {
                ticking = false;
                maybeContinue();
            });
        };
        window.addEventListener("scroll", onScroll, { passive: true });
        window.addEventListener("resize", onScroll);
        maybeContinue();
    }
})();
