(() => {
    const page = document.querySelector(".profile-page");
    const tabs = page?.querySelector(".profile-tabs");
    if (!page || !tabs || document.querySelector("[data-referral-tab]")) return;

    const loadStyles = () => {
        if (document.querySelector("link[data-profile-referrals-styles]")) return;
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "/static/front/css/profile-referrals.css";
        link.dataset.profileReferralsStyles = "true";
        document.head.appendChild(link);
    };

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const formatDate = (value) => {
        if (!value) return "—";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "—";
        return new Intl.DateTimeFormat("ru-RU", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        }).format(date);
    };

    const currentTab = () => new URL(window.location.href).searchParams.get("tab") || "profile";

    const activateReferral = (panel, tab) => {
        page.querySelectorAll("[data-profile-tab-panel]").forEach((item) => item.classList.remove("is-active"));
        tabs.querySelectorAll("a").forEach((item) => item.classList.remove("is-active"));
        panel.classList.add("is-active");
        tab.classList.add("is-active");
    };

    const deactivateReferral = (panel, tab) => {
        panel.classList.remove("is-active");
        tab.classList.remove("is-active");
    };

    const copyText = async (value) => {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(value);
            return;
        }
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
    };

    fetch("/cabinet/referrals/stats/", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
    })
        .then(async (response) => {
            if (response.status === 403) return null;
            const payload = await response.json();
            if (!response.ok || !payload?.ok) throw new Error(payload?.error || "Не удалось загрузить реферальную статистику.");
            return payload;
        })
        .then((payload) => {
            if (!payload) return;
            loadStyles();

            const tab = document.createElement("a");
            tab.href = `${window.location.pathname}?tab=referrals`;
            tab.dataset.referralTab = "";
            tab.textContent = "Рефералы";
            tabs.insertBefore(tab, tabs.querySelector('a[href*="tab=settings"]') || null);

            const rows = (payload.recent || []).map((item) => {
                const userLabel = item.username ? `@${escapeHtml(item.username)}` : escapeHtml(item.name);
                const status = item.subscribed
                    ? '<span class="profile-referral-status is-subscribed">Подписался</span>'
                    : '<span class="profile-referral-status">Только переход</span>';
                return `
                    <article class="profile-referral-row">
                        <div class="profile-referral-user">
                            <strong>${userLabel}</strong>
                            <span>${item.username ? escapeHtml(item.name) : "Без входа в аккаунт"}</span>
                        </div>
                        <div class="profile-referral-metric"><strong>${escapeHtml(item.visits_count)}</strong><span>переходов</span></div>
                        <div class="profile-referral-metric"><strong>${formatDate(item.first_seen_at)}</strong><span>первый переход</span></div>
                        <div class="profile-referral-metric"><strong>${item.subscribed ? formatDate(item.subscribed_at) : "—"}</strong><span>подписка</span></div>
                        ${status}
                    </article>`;
            }).join("");

            const panel = document.createElement("section");
            panel.className = "profile-tab-panel";
            panel.dataset.profileTabPanel = "referrals";
            panel.id = "profile-tab-referrals";
            panel.innerHTML = `
                <div class="profile-referrals-shell">
                    <section class="profile-referrals-hero">
                        <div>
                            <p class="eyebrow">Ваша реферальная ссылка</p>
                            <h2>Приводите аудиторию в свой профиль</h2>
                            <p>Переход фиксируется по уникальной сессии. Если человек после перехода подпишется на вас, это попадёт в конверсию.</p>
                        </div>
                        <div class="profile-referral-link-wrap">
                            <input class="profile-referral-link" type="text" readonly value="${escapeHtml(payload.referral_url)}" aria-label="Реферальная ссылка">
                            <button class="profile-referral-copy" type="button" data-referral-copy>Скопировать</button>
                        </div>
                    </section>

                    <section class="profile-referrals-stats" aria-label="Реферальная статистика">
                        <article class="profile-referral-stat is-accent"><span>Уникальные посетители</span><strong>${escapeHtml(payload.visitors_count)}</strong></article>
                        <article class="profile-referral-stat"><span>Все переходы</span><strong>${escapeHtml(payload.clicks_count)}</strong></article>
                        <article class="profile-referral-stat"><span>Подписались после ссылки</span><strong>${escapeHtml(payload.subscriptions_count)}</strong></article>
                        <article class="profile-referral-stat"><span>Конверсия в подписку</span><strong>${escapeHtml(payload.conversion)}%</strong></article>
                    </section>

                    <section class="profile-referrals-recent">
                        <div class="profile-referrals-recent-head">
                            <div><p class="eyebrow">Последние переходы</p><div class="profile-referrals-recent-title heading-style-h3">Кто пришёл по ссылке</div></div>
                            <span>Последние ${Math.min((payload.recent || []).length, 40)}</span>
                        </div>
                        <div class="profile-referral-list">
                            ${rows || '<div class="profile-referrals-empty">Переходов по вашей ссылке пока нет.</div>'}
                        </div>
                    </section>
                </div>`;
            page.appendChild(panel);

            const copyButton = panel.querySelector("[data-referral-copy]");
            copyButton?.addEventListener("click", async () => {
                const original = copyButton.textContent;
                try {
                    await copyText(payload.referral_url);
                    copyButton.textContent = "Скопировано";
                    copyButton.classList.add("is-copied");
                } catch (_) {
                    copyButton.textContent = "Не удалось";
                }
                window.setTimeout(() => {
                    copyButton.textContent = original;
                    copyButton.classList.remove("is-copied");
                }, 1600);
            });

            tab.addEventListener("click", (event) => {
                event.preventDefault();
                const url = new URL(tab.href, window.location.href);
                window.history.pushState({}, "", url);
                activateReferral(panel, tab);
            });

            tabs.querySelectorAll("a:not([data-referral-tab])").forEach((link) => {
                link.addEventListener("click", () => deactivateReferral(panel, tab));
            });

            window.addEventListener("popstate", () => {
                if (currentTab() === "referrals") activateReferral(panel, tab);
                else deactivateReferral(panel, tab);
            });

            if (currentTab() === "referrals") activateReferral(panel, tab);
        })
        .catch((error) => {
            if (currentTab() !== "referrals") return;
            console.error(error);
        });
})();
