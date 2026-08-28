(() => {
    const grid = document.querySelector("[data-matches-grid]");
    const sentinel = document.querySelector("[data-matches-lazy]");
    if (!grid || !sentinel) return;

    const button = sentinel.querySelector("[data-matches-lazy-button]");
    const status = sentinel.querySelector("[data-matches-lazy-status]");
    let nextPage = Number.parseInt(sentinel.dataset.nextPage || "", 10) || null;
    let loading = false;
    let refreshing = false;
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
        if (button) button.setAttribute("disabled", "disabled");
    };

    const revive = (page) => {
        nextPage = Number.parseInt(page || "", 10) || null;
        sentinel.dataset.nextPage = nextPage ? String(nextPage) : "";
        sentinel.classList.toggle("is-done", !nextPage);
        if (button) {
            button.toggleAttribute("disabled", !nextPage);
            if (nextPage) button.textContent = "Показать ещё";
        }
    };

    const requestUrl = (page) => {
        const url = new URL(window.location.href);
        url.searchParams.delete("window");
        url.searchParams.delete("lazy");
        url.searchParams.set("page", String(page));
        return `${url.pathname}?${url.searchParams.toString()}`;
    };

    const windowRequestUrl = (windowSize) => {
        const url = new URL(window.location.href);
        url.searchParams.delete("page");
        url.searchParams.set("lazy", "1");
        url.searchParams.set("window", String(windowSize));
        return `${url.pathname}?${url.searchParams.toString()}`;
    };

    const parseNodes = (html) => {
        if (!html || !html.trim()) return [];
        const template = document.createElement("template");
        template.innerHTML = html.trim();
        return Array.from(template.content.children);
    };

    const dispatchAppended = (nodes) => {
        if (!nodes.length) return;
        document.dispatchEvent(new CustomEvent("matches:appended", { detail: { nodes } }));
    };

    const appendHtml = (html) => {
        const existingIds = new Set(
            Array.from(grid.querySelectorAll("[data-match-shell-id]"))
                .map((node) => node.dataset.matchShellId)
                .filter(Boolean),
        );
        const nodes = parseNodes(html).filter((node) => {
            const id = node.dataset.matchShellId;
            return !id || !existingIds.has(id);
        });

        nodes.forEach((node, index) => {
            node.classList.add("is-lazy-added");
            node.style.animationDelay = `${Math.min(index, 8) * 35}ms`;
            grid.appendChild(node);
        });
        dispatchAppended(nodes);
        return nodes;
    };

    const reconcileHtml = (html) => {
        const desired = parseNodes(html);
        const existing = new Map(
            Array.from(grid.querySelectorAll(":scope > [data-match-shell-id]"))
                .map((node) => [node.dataset.matchShellId, node]),
        );
        const before = new Map(Array.from(existing.values()).map((node) => [node, node.getBoundingClientRect()]));
        const used = new Set();
        const added = [];

        desired.forEach((freshNode, index) => {
            const id = freshNode.dataset.matchShellId;
            const current = id ? existing.get(id) : null;
            const node = current || freshNode;
            if (current) {
                current.classList.toggle("is-watched", freshNode.classList.contains("is-watched"));
                const currentButton = current.querySelector("[data-match-watch-toggle]");
                const freshButton = freshNode.querySelector("[data-match-watch-toggle]");
                if (currentButton && freshButton) {
                    currentButton.classList.toggle("is-watching", freshButton.classList.contains("is-watching"));
                    currentButton.setAttribute("aria-pressed", freshButton.getAttribute("aria-pressed") || "false");
                }
            } else {
                node.classList.add("is-lazy-added");
                node.style.animationDelay = `${Math.min(index, 8) * 25}ms`;
                added.push(node);
            }
            used.add(id);
            grid.appendChild(node);
        });

        existing.forEach((node, id) => {
            if (!used.has(id)) node.remove();
        });

        if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            requestAnimationFrame(() => {
                Array.from(grid.querySelectorAll(":scope > [data-match-shell-id]")).forEach((node) => {
                    const oldRect = before.get(node);
                    if (!oldRect) return;
                    const newRect = node.getBoundingClientRect();
                    const dx = oldRect.left - newRect.left;
                    const dy = oldRect.top - newRect.top;
                    if (!dx && !dy) return;
                    node.animate(
                        [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "translate(0, 0)" }],
                        { duration: 300, easing: "cubic-bezier(.2,.8,.2,1)" },
                    );
                });
            });
        }
        dispatchAppended(added);
    };

    const maybeContinue = () => {
        if (!autoEnabled || loading || refreshing || !nextPage) return;
        const rect = sentinel.getBoundingClientRect();
        if (rect.top <= window.innerHeight + 650) window.setTimeout(loadNext, 90);
    };

    const loadNext = async () => {
        if (loading || refreshing || !nextPage) return;
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
                headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
            });
            if (!response.ok) throw new Error("lazy-load-request-failed");
            const payload = await response.json();
            if (!payload?.ok) throw new Error("lazy-load-response-invalid");

            appendHtml(payload.html || "");
            sentinel.dataset.currentPage = String(payload.page || requestedPage);
            if (payload.has_next && payload.next_page) {
                revive(payload.next_page);
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
            if (button && nextPage) button.removeAttribute("disabled");
            maybeContinue();
        }
    };

    const refreshLoadedWindow = async () => {
        if (refreshing) return;
        if (loading) {
            window.setTimeout(refreshLoadedWindow, 180);
            return;
        }

        const loadedCount = Math.max(18, grid.querySelectorAll(":scope > [data-match-shell-id]").length);
        refreshing = true;
        setStatus("Обновляем порядок матчей");
        try {
            const response = await fetch(windowRequestUrl(loadedCount), {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
            });
            if (!response.ok) throw new Error("watch-refresh-request-failed");
            const payload = await response.json();
            if (!payload?.ok) throw new Error("watch-refresh-response-invalid");

            reconcileHtml(payload.html || "");
            sentinel.dataset.currentPage = String(payload.page || 1);
            if (payload.has_next && payload.next_page) revive(payload.next_page);
            else finish();
            setStatus("");
            autoEnabled = true;
        } catch (error) {
            setStatus("");
        } finally {
            refreshing = false;
            maybeContinue();
        }
    };

    button?.addEventListener("click", () => {
        autoEnabled = true;
        loadNext();
    });

    document.addEventListener("matches:watch-changed", refreshLoadedWindow);

    if ("IntersectionObserver" in window) {
        observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting) && autoEnabled) loadNext();
        }, { root: null, rootMargin: "650px 0px", threshold: 0.01 });
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
