(() => {
    const forms = document.querySelectorAll("[data-site-search-form]");
    if (!forms.length) return;

    const compact = () => window.matchMedia("(max-width: 760px)").matches;
    const onResultsPage = document.body.classList.contains("site-search-page");

    const highlight = (node, value, term) => {
        const start = value.toLocaleLowerCase().indexOf(term.toLocaleLowerCase());
        if (start < 0 || !term) {
            node.textContent = value;
            return;
        }
        node.append(document.createTextNode(value.slice(0, start)));
        const mark = document.createElement("mark");
        mark.textContent = value.slice(start, start + term.length);
        node.append(mark, document.createTextNode(value.slice(start + term.length)));
    };

    forms.forEach((form) => {
        const input = form.querySelector("[data-site-search-input]");
        const clear = form.querySelector("[data-site-search-clear]");
        const panel = form.querySelector("[data-site-search-suggestions]");
        if (!input || !panel) return;

        let timer;
        let controller;
        let sequence = 0;

        const close = () => {
            panel.hidden = true;
            panel.replaceChildren();
            input.setAttribute("aria-expanded", "false");
        };

        const text = (tag, value, className) => {
            const el = document.createElement(tag);
            el.className = className || "";
            el.textContent = value;
            return el;
        };

        const render = (data) => {
            panel.replaceChildren();
            const labels = { matches: "Матчи", cappers: "Капперы", tournaments: "Турниры" };
            for (const [key, label] of Object.entries(labels)) {
                const rows = data.groups?.[key] || [];
                if (!rows.length) continue;

                const section = document.createElement("section");
                section.className = "site-search-suggest-group";
                section.setAttribute("aria-label", label);
                section.append(text("div", label, "site-search-suggest-label"));

                for (const item of rows) {
                    const link = document.createElement("a");
                    link.className = "site-search-suggest-row";
                    link.href = item.url;
                    const avatar = document.createElement("span");
                    avatar.className = "site-search-suggest-icon";
                    if (item.avatar) {
                        const img = document.createElement("img");
                        img.src = item.avatar;
                        img.alt = "";
                        img.width = 42;
                        img.height = 42;
                        avatar.append(img);
                    } else {
                        avatar.textContent = item.initials || item.icon || "🏆";
                    }
                    const copy = document.createElement("span");
                    copy.className = "site-search-suggest-copy";
                    const title = document.createElement("strong");
                    highlight(title, item.title, data.query);
                    copy.append(title, text("small", item.subtitle));
                    link.append(avatar, copy);
                    if (item.count) link.append(text("span", String(item.count), "site-search-suggest-count"));
                    const arrow = text("span", "›", "site-search-suggest-arrow");
                    arrow.setAttribute("aria-hidden", "true");
                    link.append(arrow);
                    section.append(link);
                }
                panel.append(section);
            }

            if (!data.total) {
                panel.append(text("p", "Совпадений пока нет", "site-search-suggest-empty"));
            } else {
                const all = document.createElement("a");
                all.className = "site-search-suggest-all";
                const url = new URL(form.action, window.location.href);
                url.searchParams.set("q", data.query);
                all.href = url.href;
                all.textContent = `Показать все ${data.total} результата →`;
                panel.append(all);
            }
            panel.hidden = false;
            input.setAttribute("aria-expanded", "true");
        };

        const search = async () => {
            const q = input.value.trim();
            clear.hidden = !q;
            if (q.length < 2) {
                controller?.abort();
                close();
                return;
            }
            controller?.abort();
            controller = new AbortController();
            const current = ++sequence;
            try {
                const url = new URL(form.dataset.suggestionsUrl, window.location.href);
                url.searchParams.set("q", q);
                const response = await fetch(url, { signal: controller.signal, credentials: "same-origin" });
                if (!response.ok) throw new Error("Search unavailable");
                const data = await response.json();
                if (current === sequence && input.value.trim() === q) render(data);
            } catch (error) {
                if (error.name !== "AbortError") close();
            }
        };

        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        input.addEventListener("input", () => {
            window.clearTimeout(timer);
            clear.hidden = !input.value;
            timer = window.setTimeout(search, 260);
        });
        input.addEventListener("focus", () => {
            if (compact() && !onResultsPage) {
                window.location.assign(form.action);
                return;
            }
            if (input.value.trim().length >= 2) search();
        });
        input.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                close();
                input.blur();
            }
        });
        clear.addEventListener("click", () => {
            window.clearTimeout(timer);
            controller?.abort();
            input.value = "";
            clear.hidden = true;
            close();
            input.focus();
        });
        form.addEventListener("submit", (event) => {
            if (!input.value.trim()) {
                event.preventDefault();
                input.focus();
            }
        });
        document.addEventListener("pointerdown", (event) => {
            if (!form.contains(event.target)) close();
        });
        clear.hidden = !input.value;

        if (compact() && onResultsPage && !input.value) {
            window.requestAnimationFrame(() => input.focus());
        }
    });

    const filters = document.querySelector("[data-site-search-filters]");
    filters?.addEventListener("change", () => filters.requestSubmit());

    const query = new URLSearchParams(window.location.search).get("q");
    if (query && onResultsPage) {
        document.querySelectorAll("[data-site-search-highlight]").forEach((node) => {
            const value = node.textContent;
            node.replaceChildren();
            highlight(node, value, query);
        });
    }
})();
