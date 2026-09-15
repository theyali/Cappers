from pathlib import Path


profile_path = Path("templates/cabinet/profile.html")
profile = profile_path.read_text()

hero_start = '            <div class="profile-hero long-bg long-bg-5{% if not request.user.is_analyst %} is-reader{% endif %}">'
panel_marker = '            <section class="profile-tab-panel {% if active_tab == \'profile\' %}is-active{% endif %}" id="profile-tab-profile" data-profile-tab-panel="profile">'
start = profile.index(hero_start)
end = profile.index(panel_marker, start)

new_hero = r'''            <div class="profile-dashboard-head{% if not request.user.is_analyst %} is-reader{% endif %}">
                <div class="profile-hero long-bg long-bg-5{% if not request.user.is_analyst %} is-reader{% endif %}">
                    <div class="profile-identity">
                        <div class="profile-avatar-wrap">
                            <div class="profile-avatar" id="profileAvatar" data-skeleton-image>
                                {% if analyst_profile and analyst_profile.avatar %}
                                    <img src="{{ analyst_profile.avatar.url }}" alt="Аватар {{ request.user.username }}" id="profileAvatarImage" width="128" height="128" decoding="async">
                                {% elif request.user.avatar %}
                                    <img src="{{ request.user.avatar.url }}" alt="Аватар {{ request.user.username }}" id="profileAvatarImage" width="128" height="128" decoding="async">
                                {% else %}
                                    <span id="profileAvatarFallback">{{ request.user.username|first|upper }}</span>
                                {% endif %}
                            </div>
                            {% if analyst_profile %}
                                <label class="avatar-upload-button" for="avatarUploadInput" title="Изменить аватар" aria-label="Изменить аватар">
                                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h3l1.4-2h7.2L17 7h3v12H4z"></path><circle cx="12" cy="13" r="3.2"></circle></svg>
                                </label>
                                <input id="avatarUploadInput" class="avatar-upload-input" type="file" accept="image/jpeg,image/png,image/webp">
                            {% endif %}
                        </div>

                        <div class="profile-title-block">
                            <span class="profile-role">{{ request.user.get_role_display }}</span>
                            <div class="profile-name-line">
                                <h1>
                                    {% if analyst_profile and analyst_profile.display_name %}
                                        {{ analyst_profile.display_name }}
                                    {% elif request.user.get_full_name %}
                                        {{ request.user.get_full_name }}
                                    {% else %}
                                        {{ request.user.username }}
                                    {% endif %}
                                </h1>
                                {% if analyst_profile and analyst_profile.is_verified %}
                                <span class="capper-verified-badge" title="Проверенный каппер" aria-label="Проверенный каппер">
                                    <svg viewBox="0 0 16 16" aria-hidden="true">
                                        <path class="capper-verified-bg" d="M10.067.87a2.89 2.89 0 0 0-4.134 0l-.622.638-.89-.011a2.89 2.89 0 0 0-2.924 2.924l.01.89-.636.622a2.89 2.89 0 0 0 0 4.134l.637.622-.011.89a2.89 2.89 0 0 0 2.924 2.924l.89-.01.622.636a2.89 2.89 0 0 0 4.134 0l.622-.637.89.011a2.89 2.89 0 0 0 2.924-2.924l-.01-.89.636-.622a2.89 2.89 0 0 0 0-4.134l-.637-.622.011-.89a2.89 2.89 0 0 0-2.924-2.924l-.89.01z"></path>
                                        <path class="capper-verified-check" d="M10.354 6.854a.5.5 0 0 0-.708-.708L7 8.793 5.854 7.646a.5.5 0 1 0-.708.708l1.5 1.5a.5.5 0 0 0 .708 0z"></path>
                                    </svg>
                                </span>
                                {% endif %}
                            </div>
                            <span class="profile-username">@{{ request.user.username }}</span>
                            <p class="profile-summary">
                                {% if analyst_profile and analyst_profile.bio %}
                                    {{ analyst_profile.bio|truncatechars:125 }}
                                {% elif request.user.is_analyst %}
                                    Добавьте описание, чтобы аудитория лучше понимала ваш подход к прогнозам.
                                {% else %}
                                    Ваш профиль на КапперХаб.
                                {% endif %}
                            </p>

                            <div class="profile-hero-actions">
                                <a class="profile-hero-edit" href="{% url 'cabinet:profile' %}?tab=settings" data-profile-tab-link>Редактировать</a>
                                <div class="profile-hero-meta" aria-label="Краткая статистика профиля">
                                    <span class="profile-meta-item">
                                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 2v3M17 2v3M3 9h18M5 5h14a2 2 0 0 1 2 2v12H3V7a2 2 0 0 1 2-2Z"></path></svg>
                                        <span>На платформе с {{ request.user.date_joined|date:"d.m.Y" }}</span>
                                    </span>
                                    {% if request.user.is_analyst %}
                                    <a class="profile-meta-item" href="{% url 'cabinet:profile' %}?tab=followers" data-profile-tab-link>
                                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M22 21v-2a4 4 0 0 0-3-3.87"></path></svg>
                                        <strong>{{ followers_count }}</strong><span>подписчиков</span>
                                    </a>
                                    <a class="profile-meta-item" href="{% url 'cabinet:profile' %}?tab=predictions" data-profile-tab-link>
                                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3v18h18"></path><path d="m19 9-5 5-4-4-4 4"></path></svg>
                                        <strong>{{ predictions_count }}</strong><span>прогнозов</span>
                                    </a>
                                    {% endif %}
                                </div>
                            </div>
                            <div class="avatar-upload-status" id="profileAvatarStatus" aria-live="polite"></div>
                        </div>
                    </div>

                    {% if request.user.is_analyst %}
                    <section class="profile-hero-status" aria-label="Статус и заполнение профиля">
                        <div class="profile-status-heading">
                            <span class="profile-status-crown" aria-hidden="true">♛</span>
                            <div>
                                <small>Ваш статус</small>
                                <strong>{% if analyst_profile.is_vip %}PRO-АНАЛИТИК{% else %}АНАЛИТИК{% endif %}</strong>
                            </div>
                        </div>

                        <div class="profile-status-completion">
                            <div><span>Заполненность профиля</span><strong>{{ profile_completion }}%</strong></div>
                            <progress class="profile-status-progress" max="100" value="{{ profile_completion }}">{{ profile_completion }}%</progress>
                        </div>

                        <ul class="profile-status-checklist">
                            <li{% if analyst_profile.avatar or request.user.avatar %} class="is-done"{% endif %}><span aria-hidden="true">✓</span>Фото профиля</li>
                            <li{% if analyst_profile.bio %} class="is-done"{% endif %}><span aria-hidden="true">✓</span>Описание</li>
                            <li{% if analyst_profile.social_links %} class="is-done"{% endif %}><span aria-hidden="true">✓</span>Соцсети</li>
                            <li{% if predictions_count %} class="is-done"{% endif %}><span aria-hidden="true">✓</span>Статистика</li>
                            <li{% if analyst_profile.is_verified %} class="is-done"{% endif %}><span aria-hidden="true">✓</span>Подтверждение личности</li>
                            <li{% if analyst_profile.is_public %} class="is-done"{% endif %}><span aria-hidden="true">✓</span>Публичный профиль</li>
                        </ul>

                        {% if analyst_profile.is_verified %}
                            <a class="profile-status-action is-complete" href="{% url 'cabinet:profile' %}?tab=settings" data-profile-tab-link>Профиль подтверждён</a>
                        {% elif analyst_profile.verification_requested_at %}
                            <span class="profile-status-action is-pending">Запрос на проверке</span>
                        {% elif verification_requirements.can_request %}
                            <form method="post" action="{% url 'cabinet:request_verification' %}">
                                {% csrf_token %}
                                <button class="profile-status-action" type="submit">Запросить проверку</button>
                            </form>
                        {% else %}
                            <a class="profile-status-action" href="{% url 'cabinet:profile' %}?tab=settings" data-profile-tab-link>Улучшить профиль</a>
                        {% endif %}
                    </section>
                    {% endif %}
                </div>

                {% if request.user.is_analyst %}
                <aside class="profile-pro-promo" aria-label="Возможности PRO">
                    <div class="profile-pro-visual" data-skeleton-image>
                        <img src="{% static 'front/svgs/trophy.svg' %}" width="180" height="180" alt="" decoding="async">
                    </div>
                    <div class="profile-pro-copy">
                        <span>PRO</span>
                        <h2>{% if analyst_profile.is_vip %}PRO уже активен{% else %}Больше возможностей с PRO{% endif %}</h2>
                        <ul>
                            <li>Расширенная аналитика</li>
                            <li>Глубокая статистика</li>
                            <li>Приоритет в рейтинге</li>
                            <li>Эксклюзивные турниры</li>
                        </ul>
                    </div>
                    <a class="profile-pro-action" href="{% url 'cabinet:profile' %}?tab=settings" data-profile-tab-link>{% if analyst_profile.is_vip %}Настройки PRO{% else %}Перейти на PRO{% endif %}</a>
                </aside>
                {% endif %}
            </div>

'''

profile = profile[:start] + new_hero + profile[end:]
old_dashboard = '                    {% include "cabinet/_profile_dashboard.html" %}'
if old_dashboard not in profile:
    raise RuntimeError("Old profile dashboard include was not found")
profile = profile.replace(old_dashboard, '                    {# Аналитические блоки добавляем поэтапно со второго шага редизайна. #}', 1)
profile_path.write_text(profile)

base_path = Path("templates/base.html")
base = base_path.read_text()
base = base.replace('    <link rel="stylesheet" href="{% static \'front/css/temp.css\' %}">\n', '')
base_path.write_text(base)

js_path = Path("front/static/front/js/profile.js")
js = js_path.read_text()
old_js = '''        if (!image) {\n            image = document.createElement("img");\n            image.id = "profileAvatarImage";\n            image.alt = "Аватар профиля";\n            if (fallback) fallback.remove();\n            avatar.appendChild(image);\n        }\n\n        image.src = `${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`;'''
new_js = '''        if (!image) {\n            image = document.createElement("img");\n            image.id = "profileAvatarImage";\n            image.alt = "Аватар профиля";\n            image.width = 128;\n            image.height = 128;\n            image.decoding = "async";\n            if (fallback) fallback.remove();\n            avatar.appendChild(image);\n        }\n\n        image.width = 128;\n        image.height = 128;\n        image.src = `${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`;\n        window.CappersSkeleton?.watchImage(avatar);'''
if old_js not in js:
    raise RuntimeError("Avatar replacement block was not found")
js_path.write_text(js.replace(old_js, new_js, 1))

css_path = Path("front/static/front/css/main.css")
css = css_path.read_text()
profile_marker = "/* Legacy source: front/static/front/css/profile.css */"
profile_marker_at = css.index(profile_marker)
hero_css_start = css.index(".profile-page {", profile_marker_at)
layout_css_start = css.index(".profile-layout {", hero_css_start)

new_profile_css = r'''.profile-page {
    display: grid;
}

.profile-dashboard-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 310px;
    gap: 14px;
    align-items: stretch;
    margin-bottom: 18px;
}

.profile-dashboard-head.is-reader {
    grid-template-columns: minmax(0, 1fr);
}

.profile-page .profile-hero {
    position: relative;
    min-width: 0;
    min-height: 302px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(280px, 338px);
    align-items: stretch;
    gap: 24px;
    padding: 24px;
    overflow: hidden;
    border-radius: 22px;
    background-color: #171718;
}

.profile-page .profile-hero.is-reader {
    grid-template-columns: minmax(0, 1fr);
}

.profile-hero.tournament-detail-hero {
    position: relative;
    display: block;
    padding: 20px;
    overflow: hidden;
}

.profile-page .profile-identity {
    min-width: 0;
    max-width: 650px;
    display: flex;
    align-items: center;
    gap: 20px;
}

.profile-avatar-wrap {
    position: relative;
    flex: 0 0 auto;
}

.profile-page .profile-avatar {
    width: 128px;
    height: 128px;
    display: grid;
    place-items: center;
    overflow: hidden;
    border-radius: 28px;
    color: var(--ink);
    background: var(--yellow);
    font-size: 36px;
    font-weight: 700;
}

.profile-page .profile-avatar img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
}

.avatar-upload-input {
    display: none;
}

.profile-page .avatar-upload-button {
    position: absolute;
    right: -5px;
    bottom: -5px;
    width: 38px;
    height: 38px;
    display: grid;
    place-items: center;
    border-radius: 12px;
    color: #fff;
    background: var(--blue);
    cursor: pointer;
    transition: transform .18s ease, background .18s ease;
}

.profile-page .avatar-upload-button:hover {
    transform: translateY(-2px);
    background: #2469ff;
}

.profile-page .avatar-upload-button svg {
    width: 18px;
    height: 18px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.profile-title-block {
    min-width: 0;
}

.profile-page .profile-role {
    min-height: 25px;
    width: fit-content;
    display: inline-flex;
    align-items: center;
    padding: 0 9px;
    border-radius: 8px;
    color: #fff;
    background: var(--blue);
    font-size: 10px;
    font-weight: 700;
}

.profile-name-line {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 9px;
    margin-top: 8px;
}

.profile-page .profile-title-block h1 {
    min-width: 0;
    max-width: 100%;
    margin: 0;
    overflow: hidden;
    color: #fff;
    font-size: clamp(28px, 2.4vw, 38px);
    line-height: 1.05;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.profile-name-line .capper-verified-badge {
    width: 20px;
    height: 20px;
    flex: 0 0 20px;
}

.profile-username {
    display: block;
    margin-top: 5px;
    color: rgba(255, 255, 255, .64);
    font-size: 13px;
}

.profile-summary {
    max-width: 520px;
    margin: 12px 0 0;
    color: rgba(255, 255, 255, .72);
    font-size: 12px;
    line-height: 1.55;
}

.profile-hero-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 14px;
    margin-top: 18px;
}

.profile-hero-edit,
.profile-status-action,
.profile-pro-action {
    min-height: 40px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 14px;
    border: 0;
    border-radius: 10px;
    color: #fff;
    background: var(--blue);
    font-size: 11px;
    font-weight: 800;
    cursor: pointer;
}

.profile-hero-meta {
    min-width: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 13px;
}

.profile-meta-item {
    min-width: 0;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: rgba(255, 255, 255, .64);
    font-size: 10px;
    white-space: nowrap;
}

.profile-meta-item svg {
    width: 16px;
    height: 16px;
    flex: 0 0 16px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.profile-meta-item strong {
    color: #fff;
    font-size: 11px;
}

.avatar-upload-status {
    min-height: 16px;
    margin-top: 6px;
    color: var(--yellow);
    font-size: 10px;
}

.avatar-upload-status.is-error {
    color: #ff7479;
}

.profile-hero-status {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 13px;
    padding: 17px;
    border-radius: 18px;
    background: #171718;
}

.profile-status-heading {
    display: flex;
    align-items: center;
    gap: 10px;
}

.profile-status-crown {
    color: var(--yellow);
    font-size: 30px;
    line-height: 1;
}

.profile-status-heading small,
.profile-status-heading strong {
    display: block;
}

.profile-status-heading small {
    color: var(--muted);
    font-size: 9px;
}

.profile-status-heading strong {
    margin-top: 2px;
    color: var(--blue);
    font-size: 16px;
    letter-spacing: .02em;
}

.profile-status-completion > div {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    color: var(--muted);
    font-size: 10px;
}

.profile-status-completion strong {
    color: #fff;
    font-size: 14px;
}

.profile-status-progress {
    width: 100%;
    height: 6px;
    display: block;
    margin-top: 8px;
    overflow: hidden;
    border: 0;
    border-radius: 999px;
    appearance: none;
    background: #303033;
}

.profile-status-progress::-webkit-progress-bar {
    background: #303033;
}

.profile-status-progress::-webkit-progress-value {
    border-radius: inherit;
    background: var(--blue);
}

.profile-status-progress::-moz-progress-bar {
    border-radius: inherit;
    background: var(--blue);
}

.profile-status-checklist {
    display: grid;
    gap: 7px;
    margin: 0;
    padding: 0;
    list-style: none;
}

.profile-status-checklist li {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--muted);
    font-size: 10px;
}

.profile-status-checklist li > span {
    width: 17px;
    height: 17px;
    flex: 0 0 17px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    color: #5a5a5d;
    background: #2b2b2e;
    font-size: 10px;
}

.profile-status-checklist li.is-done {
    color: rgba(255, 255, 255, .78);
}

.profile-status-checklist li.is-done > span {
    color: var(--ink);
    background: #45d483;
}

.profile-hero-status form {
    margin: auto 0 0;
}

.profile-status-action {
    width: 100%;
    margin-top: auto;
    color: var(--ink);
    background: var(--yellow);
}

.profile-status-action.is-complete {
    color: #fff;
    background: var(--blue);
}

.profile-status-action.is-pending {
    cursor: default;
    color: rgba(255, 255, 255, .72);
    background: #303033;
}

.profile-pro-promo {
    min-width: 0;
    min-height: 302px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 18px;
    border-radius: 22px;
    background: var(--blue);
}

.profile-pro-visual {
    height: 112px;
    display: grid;
    place-items: center;
    margin: -13px -8px -2px;
}

.profile-pro-visual img {
    width: 150px;
    height: 150px;
    display: block;
    object-fit: contain;
}

.profile-pro-copy > span {
    color: var(--yellow);
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .12em;
}

.profile-pro-copy h2 {
    margin: 4px 0 0;
    color: #fff;
    font-size: 22px;
    line-height: 1.08;
}

.profile-pro-copy ul {
    display: grid;
    gap: 6px;
    margin: 12px 0 0;
    padding: 0;
    list-style: none;
}

.profile-pro-copy li {
    position: relative;
    padding-left: 17px;
    color: rgba(255, 255, 255, .84);
    font-size: 10px;
}

.profile-pro-copy li::before {
    content: "✓";
    position: absolute;
    left: 0;
    color: var(--yellow);
    font-weight: 800;
}

.profile-pro-action {
    width: fit-content;
    margin-top: auto;
    color: var(--ink);
    background: var(--yellow);
}

@media (max-width: 1380px) {
    .profile-dashboard-head {
        grid-template-columns: minmax(0, 1fr) 270px;
    }

    .profile-page .profile-hero {
        grid-template-columns: minmax(0, 1fr) 280px;
        gap: 16px;
        padding: 20px;
    }

    .profile-page .profile-avatar {
        width: 108px;
        height: 108px;
    }

    .profile-page .profile-identity {
        gap: 15px;
    }
}

@media (max-width: 1180px) {
    .profile-dashboard-head {
        grid-template-columns: minmax(0, 1fr);
    }

    .profile-page .profile-hero {
        grid-template-columns: minmax(0, 1fr) 290px;
    }

    .profile-pro-promo {
        min-height: 220px;
    }
}

@media (max-width: 820px) {
    .profile-page .profile-hero {
        grid-template-columns: minmax(0, 1fr);
        min-height: 0;
    }

    .profile-page .profile-identity {
        max-width: none;
    }

    .profile-pro-promo {
        display: none;
    }
}
'''

css = css[:hero_css_start] + new_profile_css + "\n\n" + css[layout_css_start:]

dashboard_start_marker = "/* Legacy source: front/static/front/css/capper-dashboard.css */"
dashboard_end_marker = "/* Legacy source: front/static/front/css/capper-register.css */"
if dashboard_start_marker in css:
    dashboard_start = css.index(dashboard_start_marker)
    dashboard_end = css.index(dashboard_end_marker, dashboard_start)
    css = css[:dashboard_start] + css[dashboard_end:]

temp_path = Path("front/static/front/css/temp.css")
if temp_path.exists():
    temp_css = temp_path.read_text().strip()
    if temp_css and temp_css not in css:
        css = css.rstrip() + "\n\n\n/* Consolidated former temp.css overrides */\n" + temp_css + "\n"
    temp_path.unlink()

css_path.write_text(css)

old_dashboard_path = Path("templates/cabinet/_profile_dashboard.html")
if old_dashboard_path.exists():
    old_dashboard_path.unlink()

profile_check = profile_path.read_text()
css_check = css_path.read_text()
base_check = base_path.read_text()
js_check = js_path.read_text()
assert "profile-dashboard-head" in profile_check
assert "profile-pro-promo" in profile_check
assert "profile-hero-status" in profile_check
assert 'style="' not in new_hero
assert "cabinet/_profile_dashboard.html" not in profile_check
assert "Legacy source: front/static/front/css/capper-dashboard.css" not in css_check
assert "front/css/temp.css" not in base_check
assert "CappersSkeleton?.watchImage(avatar)" in js_check
assert "width=\"128\" height=\"128\"" in profile_check
