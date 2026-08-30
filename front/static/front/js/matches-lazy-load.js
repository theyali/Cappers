(() => {
    const grid = document.querySelector("[data-matches-grid]");
    const sentinel = document.querySelector("[data-matches-lazy]");
    if (!grid || !sentinel) return;

    const button = sentinel.querySelector("[data-matches-lazy-button]");
    const status = sentinel.querySelector("[data-matches-lazy-status]");
    const gridPanel = grid.closest("[data-content-view-panel]");
    let nextPage = Number.parseInt(sentinel.dataset.nextPage || "", 10) || null;
    let loading = false;
    let refreshing = false;
    let autoEnabled = true;
    let observer = null;

    const setStatus = (message) => {
        if (status) status.textContent = message;
    };

    const isGridActive = () => !gridPanel || !gridPanel.hidden;

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
        if (!isGridActive() || !autoEnabled || loading || refreshing || !nextPage) return;
        const rect = sentinel.getBoundingClientRect();
        if (rect.top <= window.innerHeight + 650) window.setTimeout(loadNext, 90);
    };

    const loadNext = async () => {
        if (!isGridActive() || loading || refreshing || !nextPage) return;
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
        if (!isGridActive()) return;
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

    document.addEventListener("content-view:updated", (event) => {
        if (event.detail?.mode === "grid") maybeContinue();
    });
})();

(() => {
    const table = document.querySelector("[data-matches-table-view]");
    if (!table) return;

    const tablePanel = table.closest("[data-content-view-panel]");
    const loadingSports = new Set();
    let pendingScrollSport = null;
    let observer = null;

    const isTableActive = () => !tablePanel || !tablePanel.hidden;

    const requestUrl = (sportCode, windowSize) => {
        const url = new URL(window.location.href);
        url.searchParams.delete("page");
        url.searchParams.set("lazy", "1");
        url.searchParams.set("view", "table");
        url.searchParams.set("table_sport", sportCode);
        url.searchParams.set("window", String(windowSize));
        return `${url.pathname}?${url.searchParams.toString()}`;
    };

    const parseSport = (html) => {
        const template = document.createElement("template");
        template.innerHTML = String(html || "").trim();
        const node = template.content.firstElementChild;
        return node?.matches?.("[data-table-sport-code]") ? node : null;
    };

    const setSentinelStatus = (sentinel, message) => {
        const status = sentinel?.querySelector("[data-table-sport-lazy-status]");
        if (status) status.textContent = message;
    };

    const reviveSentinels = (scope = table) => {
        scope.querySelectorAll("[data-table-sport-lazy]").forEach((sentinel) => {
            observer?.observe(sentinel);
        });
    };

    const loadSportWindow = async (details) => {
        if (!details || !details.open || !isTableActive()) return;

        const sportCode = details.dataset.tableSportCode;
        const sentinel = details.querySelector("[data-table-sport-lazy]");
        const nextWindow = Number.parseInt(sentinel?.dataset.nextWindow || "", 10);
        if (!sportCode || !sentinel || !nextWindow || loadingSports.has(sportCode)) return;

        loadingSports.add(sportCode);
        sentinel.classList.add("is-loading");
        const button = sentinel.querySelector("[data-table-sport-lazy-button]");
        button?.setAttribute("disabled", "disabled");
        if (button) button.textContent = "Загружаем...";
        setSentinelStatus(sentinel, "Загружаем матчи");

        try {
            const response = await fetch(requestUrl(sportCode, nextWindow), {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
            });
            if (!response.ok) throw new Error("table-lazy-request-failed");
            const payload = await response.json();
            if (!payload?.ok) throw new Error("table-lazy-response-invalid");

            const replacement = parseSport(payload.html);
            if (!replacement) {
                sentinel.classList.add("is-done");
                return;
            }

            replacement.open = true;
            details.replaceWith(replacement);
            window.CappersSkeleton?.watchImages(replacement);
            const rows = Array.from(replacement.querySelectorAll("[data-match-shell-id]"));
            document.dispatchEvent(new CustomEvent("matches:appended", { detail: { nodes: rows } }));
            reviveSentinels(replacement);
            if (pendingScrollSport === sportCode) settleSportAtTop(replacement);
            maybeLoadVisible();
        } catch (error) {
            setSentinelStatus(sentinel, "Не удалось загрузить матчи.");
            if (button) {
                button.textContent = "Повторить";
                button.removeAttribute("disabled");
            }
        } finally {
            sentinel.classList.remove("is-loading");
            loadingSports.delete(sportCode);
        }
    };

    const maybeLoadSentinel = (sentinel) => {
        if (!isTableActive()) return;
        const details = sentinel.closest("[data-table-sport-code]");
        if (!details?.open) return;
        const rect = sentinel.getBoundingClientRect();
        if (rect.top <= window.innerHeight + 650) window.setTimeout(() => loadSportWindow(details), 90);
    };

    const maybeLoadVisible = () => {
        table.querySelectorAll("[data-table-sport-lazy]").forEach(maybeLoadSentinel);
    };

    const sportByCode = (sportCode) => {
        if (!sportCode) return null;
        return Array.from(table.querySelectorAll("[data-table-sport-code]"))
            .find((node) => node.dataset.tableSportCode === sportCode) || null;
    };

    const stickyOffset = () => {
        const value = window.getComputedStyle(table).getPropertyValue("--content-sport-sticky-top");
        return Number.parseFloat(value) || 0;
    };

    const scrollSportToStickyTop = (details) => {
        if (!details) return;

        const top = details.getBoundingClientRect().top + window.scrollY - stickyOffset();
        window.scrollTo({ top: Math.max(0, top), behavior: "auto" });
    };

    const settleSportAtTop = (details) => {
        if (!details) return;
        const sportCode = details.dataset.tableSportCode;
        if (!sportCode) return;

        pendingScrollSport = sportCode;
        let attempts = 0;
        const settle = () => {
            const current = sportByCode(sportCode);
            if (!current) return;
            if (!current.open) current.open = true;
            scrollSportToStickyTop(current);
            attempts += 1;
            if (attempts < 8) {
                window.setTimeout(settle, attempts < 4 ? 70 : 140);
            } else if (pendingScrollSport === sportCode) {
                pendingScrollSport = null;
            }
        };

        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(settle);
        });
    };

    const nextSportAfterClose = (details) => {
        let sibling = details?.nextElementSibling;
        while (sibling) {
            if (sibling.matches?.("[data-table-sport-code]")) return sibling;
            sibling = sibling.nextElementSibling;
        }

        sibling = details?.previousElementSibling;
        while (sibling) {
            if (sibling.matches?.("[data-table-sport-code]")) return sibling;
            sibling = sibling.previousElementSibling;
        }
        return null;
    };

    table.addEventListener("click", (event) => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest("[data-table-sport-lazy-button]");
        if (!button) return;
        const details = button.closest("[data-table-sport-code]");
        loadSportWindow(details);
    });

    table.addEventListener("toggle", (event) => {
        const details = event.target;
        if (!(details instanceof HTMLDetailsElement)) return;
        if (!details.matches("[data-table-sport-code]")) return;
        if (!details.open) {
            const nextSport = nextSportAfterClose(details);
            settleSportAtTop(nextSport);
            return;
        }

        const sentinel = details.querySelector("[data-table-sport-lazy]");
        if (sentinel) maybeLoadSentinel(sentinel);
    }, true);

    if ("IntersectionObserver" in window) {
        observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) maybeLoadSentinel(entry.target);
            });
        }, { root: null, rootMargin: "650px 0px", threshold: 0.01 });
        reviveSentinels();
    } else {
        let ticking = false;
        const onScroll = () => {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(() => {
                ticking = false;
                maybeLoadVisible();
            });
        };
        window.addEventListener("scroll", onScroll, { passive: true });
        window.addEventListener("resize", onScroll);
    }

    document.addEventListener("content-view:updated", (event) => {
        if (event.detail?.mode === "table") maybeLoadVisible();
    });

    maybeLoadVisible();
})();
