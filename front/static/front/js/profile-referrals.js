(() => {
    const page = document.querySelector(".matches-list-panel.profile-page") || document.querySelector(".profile-page");
    const scope = page?.closest(".matches-shell") || page;
    const tabGroups = Array.from(
        scope?.querySelectorAll(".matches-tabs, .matches-table-scope-list") || [],
    ).filter((group) => group.querySelector("[data-profile-tab-link]"));
    if (!page || !tabGroups.length || document.querySelector("[data-referral-tab]")) return;

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

    const activateReferral = (panel) => {
        page.querySelectorAll("[data-profile-tab-panel]").forEach((item) => item.classList.remove("is-active"));
        scope.querySelectorAll("[data-profile-tab-link], [data-referral-tab]").forEach((item) => {
            item.classList.remove("is-active");
            item.removeAttribute("aria-current");
        });
        panel.classList.add("is-active");
        scope.querySelectorAll("[data-referral-tab]").forEach((item) => {
            item.classList.add("is-active");
            item.setAttribute("aria-current", "page");
        });
    };

    const deactivateReferral = (panel) => {
        panel.classList.remove("is-active");
        scope.querySelectorAll("[data-referral-tab]").forEach((item) => {
            item.classList.remove("is-active");
            item.removeAttribute("aria-current");
        });
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
            const referralTabs = tabGroups.map((group) => {
                const settingsTab = group.querySelector('a[href*="tab=settings"]');
                const tab = settingsTab ? settingsTab.cloneNode(true) : document.createElement("a");
                tab.href = `${window.location.pathname}?tab=referrals`;
                tab.dataset.referralTab = "";
                tab.removeAttribute("data-profile-tab-link");
                tab.classList.remove("is-active");
                tab.removeAttribute("aria-current");
                const label = tab.querySelector(".matches-table-scope-copy");
                if (label) label.textContent = "Рефералы";
                else tab.textContent = "Рефералы";
                group.insertBefore(tab, settingsTab || null);
                return tab;
            });

            const rows = (payload.recent || []).map((item) => {
                const userLabel = item.username ? `@${escapeHtml(item.username)}` : escapeHtml(item.name);
                const status = item.subscribed
                    ? '<span class="profile-referral-status is-subscribed">Подписался</span>'
                    : item.registered
                        ? '<span class="profile-referral-status is-subscribed">Зарегистрировался</span>'
                        : '<span class="profile-referral-status">Только переход</span>';
                return `
                    <article class="profile-referral-row">
                        <div class="profile-referral-user">
                            <strong>${userLabel}</strong>
                            <span>${item.username ? escapeHtml(item.name) : "Без входа в аккаунт"}</span>
                        </div>
                        <div class="profile-referral-metric"><strong>${escapeHtml(item.visits_count)}</strong><span>переходов</span></div>
                        <div class="profile-referral-metric"><strong>${formatDate(item.first_seen_at)}</strong><span>первый переход</span></div>
                        <div class="profile-referral-metric"><strong>${item.registered ? formatDate(item.registered_at) : "—"}</strong><span>регистрация</span></div>
                        ${status}
                    </article>`;
            }).join("");
            const earningsStat = payload.can_earn_referrals
                ? `<article class="profile-referral-stat"><span>Заработано</span><strong>${escapeHtml(payload.referral_income_display)} ₽</strong></article>`
                : "";

            const panel = document.createElement("section");
            panel.className = "profile-tab-panel";
            panel.dataset.profileTabPanel = "referrals";
            panel.id = "profile-tab-referrals";
            panel.innerHTML = `
                <div class="profile-referrals-shell">
                    <section class="profile-referrals-hero">
                        <div>
                            <p class="eyebrow">Ваша реферальная ссылка</p>
                            <h2>Приглашайте пользователей на платформу</h2>
                            <p>Переход фиксируется по уникальной сессии. Если человек после перехода зарегистрируется, это попадёт в конверсию.</p>
                        </div>
                        <div class="profile-referral-link-wrap">
                            <input class="profile-referral-link" type="text" readonly value="${escapeHtml(payload.referral_url)}" aria-label="Реферальная ссылка">
                            <button class="profile-referral-copy" type="button" data-referral-copy>Скопировать</button>
                        </div>
                    </section>

                    <section class="profile-referrals-stats" aria-label="Реферальная статистика">
                        <article class="profile-referral-stat is-accent"><span>Уникальные посетители</span><strong>${escapeHtml(payload.visitors_count)}</strong></article>
                        <article class="profile-referral-stat"><span>Все переходы</span><strong>${escapeHtml(payload.clicks_count)}</strong></article>
                        <article class="profile-referral-stat"><span>Зарегистрировались</span><strong>${escapeHtml(payload.registrations_count)}</strong></article>
                        <article class="profile-referral-stat"><span>Конверсия в регистрацию</span><strong>${escapeHtml(payload.conversion)}%</strong></article>
                        ${earningsStat}
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
            const settingsPanel = page.querySelector('[data-profile-tab-panel="settings"]');
            page.insertBefore(panel, settingsPanel || null);

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

            referralTabs.forEach((tab) => tab.addEventListener("click", (event) => {
                event.preventDefault();
                const url = new URL(tab.href, window.location.href);
                window.history.pushState({}, "", url);
                activateReferral(panel);
            }));

            scope.querySelectorAll("a:not([data-referral-tab])").forEach((link) => {
                link.addEventListener("click", () => deactivateReferral(panel));
            });

            window.addEventListener("popstate", () => {
                if (currentTab() === "referrals") activateReferral(panel);
                else deactivateReferral(panel);
            });

            if (currentTab() === "referrals") activateReferral(panel);
        })
        .catch((error) => {
            if (currentTab() !== "referrals") return;
            console.error(error);
        });
})();
