(() => {
    const root = document.querySelector("[data-profile-comments]");
    if (!root) return;

    const form = root.querySelector("[data-profile-comments-form]");
    const results = root.querySelector("[data-profile-comments-results]");
    const kindInput = root.querySelector("[data-profile-comments-kind]");
    const searchInput = root.querySelector("[data-profile-comments-search]");
    const sortInput = root.querySelector("[data-profile-comments-sort]");
    const moreButton = root.querySelector("[data-profile-comments-more]");
    const remainingNode = root.querySelector("[data-profile-comments-remaining]");
    const url = root.dataset.commentsUrl || window.location.pathname;
    let loading = false;
    let searchTimer = 0;

    const params = (append = false) => {
        const data = new URLSearchParams(new FormData(form));
        data.set("offset", append ? root.dataset.nextOffset || "0" : "0");
        return data;
    };

    const syncState = (payload, append) => {
        if (!append) {
            results.innerHTML = payload.html || "";
        } else {
            const template = document.createElement("template");
            template.innerHTML = payload.html || "";
            results.append(...template.content.childNodes);
        }
        root.dataset.nextOffset = String(payload.next_offset || 0);
        root.dataset.hasMore = payload.has_more ? "true" : "false";
        if (remainingNode) remainingNode.textContent = String(payload.remaining || 0);
        if (moreButton) moreButton.hidden = !payload.has_more;
        Object.entries(payload.counts || {}).forEach(([key, value]) => {
            root.querySelectorAll(`[data-profile-comments-count="${CSS.escape(key)}"]`).forEach((node) => {
                node.textContent = String(value);
            });
        });
    };

    const load = async ({ append = false, updateUrl = true } = {}) => {
        if (loading) return;
        loading = true;
        root.classList.add("is-updating");
        try {
            const data = params(append);
            const endpoint = `${url}?${data.toString()}`;
            const response = await fetch(endpoint, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
            });
            if (!response.ok) throw new Error("Request failed");
            const payload = await response.json();
            syncState(payload, append);
            if (updateUrl && !append) {
                data.delete("offset");
                window.history.replaceState({}, "", `${url}?${data.toString()}`);
            }
        } catch (_error) {
            if (!append) {
                results.innerHTML = '<div class="profile-comments-empty"><strong>Не удалось загрузить комментарии</strong><span>Попробуйте обновить фильтр ещё раз.</span></div>';
            }
        } finally {
            loading = false;
            root.classList.remove("is-updating");
        }
    };

    root.addEventListener("click", (event) => {
        const filter = event.target.closest("[data-profile-comments-filter]");
        if (filter) {
            root.querySelectorAll("[data-profile-comments-filter]").forEach((button) => {
                button.classList.toggle("is-active", button === filter);
            });
            kindInput.value = filter.dataset.profileCommentsFilter || "received";
            void load();
            return;
        }
        const more = event.target.closest("[data-profile-comments-more]");
        if (more) void load({ append: true, updateUrl: false });
    });

    searchInput?.addEventListener("input", () => {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => void load(), 260);
    });
    sortInput?.addEventListener("change", () => void load());
    form?.addEventListener("submit", (event) => {
        event.preventDefault();
        void load();
    });

    if (moreButton && "IntersectionObserver" in window) {
        const observer = new IntersectionObserver((entries) => {
            if (!entries.some((entry) => entry.isIntersecting)) return;
            if (root.dataset.hasMore !== "true" || moreButton.hidden) return;
            void load({ append: true, updateUrl: false });
        }, { rootMargin: "240px 0px" });
        observer.observe(moreButton);
    }
})();
