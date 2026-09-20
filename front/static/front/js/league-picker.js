(() => {
    const debounce = (callback, delay = 250) => {
        let timer = null;
        return (...args) => {
            window.clearTimeout(timer);
            timer = window.setTimeout(() => callback(...args), delay);
        };
    };

    document.querySelectorAll("[data-league-picker]").forEach((picker) => {
        const modal = picker.querySelector("[data-league-picker-modal]");
        const openButton = picker.querySelector("[data-league-picker-open]");
        const hiddenInputs = picker.querySelector("[data-league-hidden-inputs]");
        const selectedContainer = picker.querySelector("[data-league-picker-selected]");
        const countLabel = picker.querySelector("[data-league-picker-count]");
        const modalCount = picker.querySelector("[data-league-picker-modal-count]");
        const searchInput = picker.querySelector("[data-league-picker-search]");
        const sportSelect = picker.querySelector("[data-league-picker-sport]");
        const countrySelect = picker.querySelector("[data-league-picker-country]");
        const topSection = picker.querySelector("[data-league-picker-top-section]");
        const topResults = picker.querySelector("[data-league-picker-top]");
        const results = picker.querySelector("[data-league-picker-results]");
        const status = picker.querySelector("[data-league-picker-status]");
        const moreButton = picker.querySelector("[data-league-picker-more]");
        const applyButton = picker.querySelector("[data-league-picker-apply]");
        const clearButton = picker.querySelector("[data-league-picker-clear]");

        if (!modal || !openButton || !hiddenInputs || !modal.dataset.searchUrl) return;

        const initialIds = Array.from(
            hiddenInputs.querySelectorAll('input[name="leagues"]')
        )
            .map((input) => Number.parseInt(input.value, 10))
            .filter(Number.isInteger);

        let selected = new Map(initialIds.map((id) => [id, { id, text: "Лига #" + id }]));
        let draft = new Map(selected);
        let currentPage = 1;
        let hasMore = false;
        let searchController = null;

        const countText = (count) => count + " выбрано";

        const updateCounts = () => {
            if (countLabel) countLabel.textContent = countText(selected.size);
            if (modalCount) modalCount.textContent = countText(draft.size);
        };

        const renderSelected = () => {
            if (!selectedContainer) return;
            selectedContainer.replaceChildren();
            selected.forEach((league) => {
                const chip = document.createElement("span");
                chip.className = "league-picker-chip";
                chip.textContent = league.text;
                selectedContainer.append(chip);
            });
            selectedContainer.hidden = selected.size === 0;
            updateCounts();
        };

        const syncHiddenInputs = () => {
            hiddenInputs.replaceChildren();
            selected.forEach((league) => {
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = "leagues";
                input.value = String(league.id);
                hiddenInputs.append(input);
            });
        };

        const refreshOptionStates = () => {
            picker.querySelectorAll("[data-league-id]").forEach((button) => {
                const id = Number.parseInt(button.dataset.leagueId, 10);
                const active = draft.has(id);
                button.setAttribute("aria-pressed", active ? "true" : "false");
                const mark = button.querySelector("i");
                if (mark) mark.textContent = active ? "✓" : "+";
            });
        };

        const optionNode = (league) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "league-picker-option";
            button.dataset.leagueId = String(league.id);
            button.setAttribute("aria-pressed", draft.has(league.id) ? "true" : "false");

            const copy = document.createElement("span");
            const title = document.createElement("strong");
            const meta = document.createElement("small");
            const mark = document.createElement("i");

            title.textContent = league.text;
            meta.textContent = [league.sport, league.country].filter(Boolean).join(" · ");
            mark.textContent = draft.has(league.id) ? "✓" : "+";

            copy.append(title, meta);
            button.append(copy, mark);

            button.addEventListener("click", () => {
                if (draft.has(league.id)) {
                    draft.delete(league.id);
                } else {
                    draft.set(league.id, league);
                }
                updateCounts();
                refreshOptionStates();
            });

            return button;
        };

        const fetchLeagues = async (params, signal) => {
            const url = new URL(modal.dataset.searchUrl, window.location.origin);
            Object.entries(params).forEach(([key, value]) => {
                if (value !== "" && value !== null && value !== undefined) {
                    url.searchParams.set(key, String(value));
                }
            });
            const response = await fetch(url, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                signal,
            });
            if (!response.ok) throw new Error("Не удалось загрузить список лиг.");
            return response.json();
        };

        const loadSelectedDetails = async () => {
            if (!initialIds.length) {
                renderSelected();
                return;
            }
            try {
                const payload = await fetchLeagues({ ids: initialIds.join(",") });
                selected = new Map(payload.results.map((league) => [league.id, league]));
                draft = new Map(selected);
            } catch (error) {
                if (error.name !== "AbortError") console.error(error);
            }
            renderSelected();
        };

        const loadTop = async () => {
            if (!topResults) return;
            topResults.replaceChildren();
            try {
                const payload = await fetchLeagues({ top: 1 });
                payload.results.slice(0, 12).forEach((league) => {
                    topResults.append(optionNode(league));
                });
                if (topSection) topSection.hidden = payload.results.length === 0;
            } catch (error) {
                if (topSection) topSection.hidden = true;
                if (error.name !== "AbortError") console.error(error);
            }
        };

        const loadResults = async ({ append = false } = {}) => {
            searchController?.abort();
            searchController = new AbortController();

            if (!append) {
                currentPage = 1;
                results?.replaceChildren();
            }
            if (status) status.textContent = "Загрузка…";
            if (moreButton) moreButton.hidden = true;

            try {
                const payload = await fetchLeagues(
                    {
                        q: searchInput?.value.trim() || "",
                        sport: sportSelect?.value || "",
                        country: countrySelect?.value || "",
                        page: currentPage,
                    },
                    searchController.signal
                );
                payload.results.forEach((league) => {
                    results?.append(optionNode(league));
                });
                hasMore = Boolean(payload.has_more);
                if (status) {
                    status.textContent =
                        !append && payload.results.length === 0
                            ? "Ничего не найдено"
                            : "";
                }
                if (moreButton) moreButton.hidden = !hasMore;
            } catch (error) {
                if (error.name === "AbortError") return;
                if (status) status.textContent = "Не удалось загрузить лиги";
                console.error(error);
            }
        };

        const closeModal = () => {
            modal.hidden = true;
            modal.classList.remove("is-open");
            document.body.classList.remove("league-picker-open");
            openButton.focus();
        };

        const openModal = () => {
            draft = new Map(selected);
            updateCounts();
            refreshOptionStates();
            modal.hidden = false;
            modal.classList.add("is-open");
            document.body.classList.add("league-picker-open");
            loadTop();
            loadResults();
            window.requestAnimationFrame(() => searchInput?.focus());
        };

        openButton.addEventListener("click", openModal);
        picker.querySelectorAll("[data-league-picker-close]").forEach((button) => {
            button.addEventListener("click", closeModal);
        });

        searchInput?.addEventListener("input", debounce(() => loadResults()));
        sportSelect?.addEventListener("change", () => loadResults());
        countrySelect?.addEventListener("change", () => loadResults());

        moreButton?.addEventListener("click", () => {
            if (!hasMore) return;
            currentPage += 1;
            loadResults({ append: true });
        });

        clearButton?.addEventListener("click", () => {
            draft.clear();
            updateCounts();
            refreshOptionStates();
        });

        applyButton?.addEventListener("click", () => {
            selected = new Map(draft);
            syncHiddenInputs();
            renderSelected();
            closeModal();
        });

        modal.addEventListener("keydown", (event) => {
            if (event.key === "Escape") closeModal();
        });

        loadSelectedDetails();
    });
})();
