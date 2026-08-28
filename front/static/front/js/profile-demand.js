(() => {
    const page = document.querySelector(".profile-page");
    const tabs = page?.querySelector(".profile-tabs");
    if (!page || !tabs || document.querySelector("[data-demand-tab]")) return;

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const loadStyles = () => {
        if (document.querySelector("link[data-profile-demand-styles]")) return;
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "/static/front/css/profile-demand.css";
        link.dataset.profileDemandStyles = "true";
        document.head.appendChild(link);
    };

    const formatDate = (value) => {
        if (!value) return { date: "Время не указано", time: "" };
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return { date: "Время не указано", time: "" };
        return {
            date: new Intl.DateTimeFormat("ru-RU", {
                day: "2-digit",
                month: "2-digit",
                year: "2-digit",
            }).format(date),
            time: new Intl.DateTimeFormat("ru-RU", {
                hour: "2-digit",
                minute: "2-digit",
            }).format(date),
        };
    };

    const currentTab = () => new URL(window.location.href).searchParams.get("tab") || "profile";

    const activate = (panel, tab) => {
        page.querySelectorAll("[data-profile-tab-panel]").forEach((item) => item.classList.remove("is-active"));
        tabs.querySelectorAll("a").forEach((item) => item.classList.remove("is-active"));
        panel.classList.add("is-active");
        tab.classList.add("is-active");
    };

    const deactivate = (panel, tab) => {
        panel.classList.remove("is-active");
        tab.classList.remove("is-active");
    };

    const teamLogo = (url, fallback) => url
        ? `<span class="profile-demand-team-logo"><img src="${escapeHtml(url)}" alt="" loading="lazy"></span>`
        : `<span class="profile-demand-team-logo">${escapeHtml((fallback || "?").slice(0, 1).toUpperCase())}</span>`;

    const rowHtml = (item) => {
        const starts = formatDate(item.starts_at);
        const ownClass = item.has_own_prediction ? " is-own" : "";
        const predictionsText = item.has_own_prediction ? "Ваш прогноз есть" : `${Number(item.predictions_count) || 0} на матч`;
        const league = [item.country, item.league].filter(Boolean).join(" · ") || "Лига не указана";
        return `
            <article class="profile-demand-row">
                <div class="profile-demand-match">
                    <div class="profile-demand-team-logos" aria-hidden="true">
                        ${teamLogo(item.home_logo, item.home_team)}
                        ${teamLogo(item.away_logo, item.away_team)}
                    </div>
                    <div class="profile-demand-match-copy">
                        <strong>${escapeHtml(item.title)}</strong>
                        <span>${escapeHtml(league)}</span>
                    </div>
                </div>
                <div class="profile-demand-date">
                    <strong>${escapeHtml(starts.date)}</strong>
                    <span>${escapeHtml(starts.time || "Начало матча")}</span>
                </div>
                <div class="profile-demand-predictions${ownClass}">
                    <strong>${escapeHtml(predictionsText)}</strong>
                    <span>прогнозы</span>
                </div>
                <div class="profile-demand-count">
                    <strong>${Number(item.requests_count) || 0}</strong>
                    <span>хотят прогноз</span>
                </div>
                <a class="profile-demand-open" href="${escapeHtml(item.url)}">Открыть матч</a>
            </article>`;
    };

    const load = async (sort = "demand") => {
        const response = await fetch(`/cabinet/prediction-demand/?sort=${encodeURIComponent(sort)}`, {
            credentials: "same-origin",
            cache: "no-store",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (response.status === 403) return null;
        const payload = await response.json();
        if (!response.ok || !payload?.ok) {
            throw new Error(payload?.error || "Не удалось загрузить спрос на прогнозы.");
        }
        return payload;
    };

    load("demand")
        .then((initial) => {
            if (!initial) return;
            loadStyles();

            const tab = document.createElement("a");
            tab.href = `${window.location.pathname}?tab=demand`;
            tab.dataset.demandTab = "";
            tab.textContent = "Спрос на прогнозы";
            tabs.insertBefore(tab, tabs.querySelector('a[href*="tab=settings"]') || null);

            const panel = document.createElement("section");
            panel.className = "profile-tab-panel";
            panel.dataset.profileTabPanel = "demand";
            panel.id = "profile-tab-demand";
            panel.innerHTML = `
                <div class="profile-demand-shell">
                    <section class="profile-demand-hero">
                        <div>
                            <p class="eyebrow">Что хотят пользователи</p>
                            <h2>Спрос на прогнозы</h2>
                            <p>Здесь только предстоящие матчи, на которые пользователи и капперы нажали «Хочу прогноз». Сначала показываем самый высокий спрос.</p>
                        </div>
                        <div class="profile-demand-summary" aria-label="Сводка спроса">
                            <article><span>Матчей со спросом</span><strong data-demand-matches-count>0</strong></article>
                            <article><span>Всего запросов</span><strong data-demand-total-count>0</strong></article>
                        </div>
                    </section>
                    <section class="profile-demand-toolbar">
                        <div class="profile-demand-toolbar-copy">
                            <strong>Матчи, где ждут ваш прогноз</strong>
                            <span>Можно сортировать по спросу или времени начала.</span>
                        </div>
                        <div class="profile-demand-sort" aria-label="Сортировка спроса">
                            <button class="is-active" type="button" data-demand-sort="demand">По спросу</button>
                            <button type="button" data-demand-sort="time">По времени</button>
                        </div>
                    </section>
                    <div class="profile-demand-list" data-demand-list></div>
                </div>`;
            page.appendChild(panel);

            const list = panel.querySelector("[data-demand-list]");
            const matchesCount = panel.querySelector("[data-demand-matches-count]");
            const totalCount = panel.querySelector("[data-demand-total-count]");
            const sortButtons = Array.from(panel.querySelectorAll("[data-demand-sort]"));

            const render = (payload) => {
                if (matchesCount) matchesCount.textContent = String(Number(payload.matches_count) || 0);
                if (totalCount) totalCount.textContent = String(Number(payload.total_requests) || 0);
                if (list) {
                    list.innerHTML = (payload.items || []).map(rowHtml).join("")
                        || '<div class="profile-demand-empty">Пока никто не запросил прогноз на предстоящие матчи.</div>';
                }
                sortButtons.forEach((button) => {
                    button.classList.toggle("is-active", button.dataset.demandSort === payload.sort);
                });
            };

            render(initial);

            sortButtons.forEach((button) => {
                button.addEventListener("click", async () => {
                    if (button.disabled || button.classList.contains("is-active")) return;
                    sortButtons.forEach((item) => { item.disabled = true; });
                    try {
                        const payload = await load(button.dataset.demandSort || "demand");
                        if (payload) render(payload);
                    } catch (error) {
                        if (list) list.innerHTML = `<div class="profile-demand-error">${escapeHtml(error?.message || "Не удалось обновить список.")}</div>`;
                    } finally {
                        sortButtons.forEach((item) => { item.disabled = false; });
                    }
                });
            });

            tab.addEventListener("click", (event) => {
                event.preventDefault();
                const url = new URL(tab.href, window.location.href);
                window.history.pushState({}, "", url);
                activate(panel, tab);
            });

            tabs.querySelectorAll("a:not([data-demand-tab])").forEach((link) => {
                link.addEventListener("click", () => deactivate(panel, tab));
            });

            window.addEventListener("popstate", () => {
                if (currentTab() === "demand") activate(panel, tab);
                else deactivate(panel, tab);
            });

            if (currentTab() === "demand") activate(panel, tab);
        })
        .catch((error) => {
            if (currentTab() === "demand") console.error(error);
        });
})();
