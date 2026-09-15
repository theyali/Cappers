from pathlib import Path
import re


def replace_once(text, pattern, replacement, *, label):
    compiled = re.compile(pattern, re.S)
    updated, count = compiled.subn(lambda _: replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"{label} matches: {count}")
    return updated


template_path = Path("templates/front/prediction_detail.html")
template = template_path.read_text(encoding="utf-8")
template_replacement = '''                <section
                    class="prediction-comments"
                    id="comments"
                    data-prediction-comments
                    data-prediction-id="{{ coupon.id }}"
                    data-author-id="{{ coupon.author_id }}"
                    data-comments-url="{% url 'front:prediction_comments' prediction_id=coupon.id %}"
                    data-delete-url-template="{% url 'front:comment_delete' comment_id=0 %}"
                    data-previous-page="{{ comments_previous_page|default:'' }}"
                    aria-labelledby="prediction-comments-title"
                >
                    <header class="prediction-comments-head">
                        <h2 id="prediction-comments-title">Комментарии</h2>
                        <span class="prediction-comments-total" aria-live="polite">
                            <strong data-comments-total>{{ coupon.comments_count }}</strong>
                            <span data-comments-total-label>комментариев</span>
                        </span>
                    </header>

                    {% if request.user.is_authenticated %}
                    <form class="prediction-comment-form" data-comment-form novalidate>
                        <span class="prediction-comment-avatar"{% if request.user.avatar %} data-skeleton-image{% endif %}>
                            {% if request.user.avatar %}
                                <img src="{{ request.user.avatar.url }}" width="52" height="52" loading="lazy" alt="">
                            {% else %}
                                {{ request.user.username|slice:":1"|upper }}
                            {% endif %}
                        </span>
                        <label for="prediction-comment-text-{{ coupon.id }}">Ваш комментарий</label>
                        <textarea
                            id="prediction-comment-text-{{ coupon.id }}"
                            name="text"
                            rows="1"
                            maxlength="1000"
                            placeholder="Напишите комментарий..."
                            data-comment-text
                        ></textarea>
                        <p class="prediction-comment-feedback" data-comment-feedback role="status" aria-live="polite" hidden></p>
                        <button
                            class="prediction-comment-submit"
                            type="submit"
                            data-comment-submit
                            aria-label="Отправить комментарий"
                            disabled
                        >
                            <svg viewBox="0 0 24 24" aria-hidden="true">
                                <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z"></path>
                            </svg>
                            <span>Отправить</span>
                        </button>
                    </form>
                    {% else %}
                    <div class="prediction-comments-auth">
                        <strong>Хотите участвовать в обсуждении?</strong>
                        <span>Войдите в аккаунт, чтобы оставить комментарий.</span>
                        <a href="{% url 'cabinet:login' %}?next={{ request.get_full_path|urlencode }}">Войти</a>
                    </div>
                    {% endif %}

                    <p class="prediction-comments-load-error" data-comments-load-error role="alert" hidden></p>

                    <div
                        class="prediction-comments-list"
                        data-comments-list
                        data-skeleton-block
                        aria-live="polite"
                        aria-busy="false"
                    >
                        {% for comment in initial_comments %}
                        <article class="prediction-comment" data-comment-id="{{ comment.id }}">
                            <span class="prediction-comment-avatar"{% if comment.user.avatar %} data-skeleton-image{% endif %}>
                                {% if comment.user.avatar %}
                                    <img src="{{ comment.user.avatar.url }}" width="52" height="52" loading="lazy" alt="">
                                {% else %}
                                    {{ comment.user.username|slice:":1"|upper }}
                                {% endif %}
                            </span>
                            <div class="prediction-comment-meta">
                                <strong>{% firstof comment.user.get_full_name comment.user.username %}</strong>
                                {% if comment.user_id == coupon.author_id %}
                                <span class="prediction-comment-author-badge">Автор</span>
                                {% endif %}
                                <time datetime="{{ comment.created_at|date:'c' }}">{{ comment.created_at|timesince }} назад</time>
                            </div>
                            {% if comment.can_delete %}
                            <button
                                class="prediction-comment-delete"
                                type="button"
                                data-comment-delete="{{ comment.id }}"
                                aria-label="Удалить комментарий пользователя {% firstof comment.user.get_full_name comment.user.username %}"
                            >
                                Удалить
                            </button>
                            {% endif %}
                            <p class="prediction-comment-text">{{ comment.text }}</p>
                        </article>
                        {% empty %}
                        <div class="prediction-comments-empty">
                            <strong>Пока нет комментариев</strong>
                            <span>Будьте первым, кто обсудит этот прогноз.</span>
                        </div>
                        {% endfor %}
                    </div>

                    <button class="prediction-comments-more" type="button" data-comments-more hidden>
                        Показать ещё комментарии
                    </button>
                </section>'''
template = replace_once(
    template,
    r'                <section\n                    class="prediction-comments".*?                </section>',
    template_replacement,
    label="prediction comments template block",
)
template_path.write_text(template, encoding="utf-8")


css_path = Path("front/static/front/css/main.css")
css = css_path.read_text(encoding="utf-8")
css_replacement = '''/* Prediction detail comments */
.prediction-comments {
    display: grid;
    gap: 22px;
    padding: 28px;
    border-radius: 24px;
    background: var(--panel);
}

.prediction-comments-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
}

.prediction-comments-head h2 {
    margin: 0;
    color: var(--text);
    font-family: var(--font-body);
    font-size: 28px;
    font-weight: 800;
    line-height: 1.1;
    letter-spacing: -.02em;
}

.prediction-comments-total {
    display: inline-flex;
    align-items: baseline;
    gap: 5px;
    color: var(--muted);
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: .04em;
    text-transform: uppercase;
    white-space: nowrap;
}

.prediction-comments-total strong {
    color: inherit;
    font-size: inherit;
    font-weight: 800;
}

.prediction-comment-form {
    position: relative;
    min-height: 56px;
    display: grid;
    grid-template-columns: 52px minmax(0, 1fr);
    align-items: center;
    gap: 14px;
}

.prediction-comment-form label,
.prediction-comment-submit span {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
}

.prediction-comment-form textarea {
    width: 100%;
    height: 56px;
    min-height: 56px;
    max-height: 120px;
    resize: none;
    padding: 17px 68px 17px 18px;
    border: 0;
    border-radius: 14px;
    outline: 0;
    color: var(--text);
    background: #29292d;
    font-size: 15px;
    line-height: 22px;
}

.prediction-comment-form textarea::placeholder {
    color: #8a8a8d;
}

.prediction-comment-form textarea:focus {
    background: #303034;
}

.prediction-comment-form textarea:disabled {
    opacity: .65;
    cursor: wait;
}

.prediction-comment-feedback,
.prediction-comments-load-error {
    margin: 0;
    color: var(--muted);
    font-size: 13px;
    line-height: 1.4;
}

.prediction-comment-feedback {
    grid-column: 2;
    padding-right: 58px;
}

.prediction-comment-feedback.is-error,
.prediction-comments-load-error {
    color: #ff6f61;
}

.prediction-comment-feedback.is-rate-limit {
    color: var(--yellow);
}

.prediction-comment-feedback.is-success {
    color: #8fd26a;
}

.prediction-comment-submit,
.prediction-comments-more,
.prediction-comments-auth a,
.prediction-comment-delete {
    border: 0;
    cursor: pointer;
    font: inherit;
}

.prediction-comment-submit {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 44px;
    height: 44px;
    display: grid;
    place-items: center;
    padding: 0;
    border-radius: 9px;
    color: #fff;
    background: var(--blue);
}

.prediction-comment-submit svg {
    width: 22px;
    height: 22px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.prediction-comment-submit:disabled {
    color: #fff;
    background: var(--blue);
    opacity: .62;
    cursor: not-allowed;
}

.prediction-comments-auth {
    display: grid;
    gap: 8px;
    padding: 16px;
    border-radius: 14px;
    background: #29292d;
}

.prediction-comments-auth span {
    color: var(--muted);
    font-size: 13px;
}

.prediction-comments-auth a {
    width: fit-content;
    min-height: 38px;
    display: inline-flex;
    align-items: center;
    padding: 0 15px;
    border-radius: 10px;
    color: #fff;
    background: var(--blue);
    font-weight: 800;
}

.prediction-comments-list {
    min-height: 300px;
    display: grid;
    align-content: start;
}

.prediction-comment {
    position: relative;
    display: grid;
    grid-template-columns: 52px minmax(0, 1fr) 32px;
    column-gap: 14px;
    row-gap: 7px;
    padding: 17px 0 21px;
    background: transparent;
}

.prediction-comment::after {
    content: "";
    position: absolute;
    right: 0;
    bottom: 0;
    left: 66px;
    height: 1px;
    background: rgba(255, 255, 255, .08);
}

.prediction-comment:last-child::after {
    display: none;
}

.prediction-comment-avatar {
    width: 52px;
    height: 52px;
    display: grid;
    place-items: center;
    overflow: hidden;
    border-radius: 50%;
    color: var(--ink);
    background: var(--yellow);
    font-size: 13px;
    font-weight: 900;
}

.prediction-comment-avatar img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
}

.prediction-comment-meta {
    min-width: 0;
    display: flex;
    align-items: center;
    align-self: start;
    flex-wrap: wrap;
    gap: 6px 10px;
    min-height: 26px;
}

.prediction-comment-meta strong {
    min-width: 0;
    overflow: hidden;
    color: var(--text);
    font-size: 15px;
    font-weight: 800;
    line-height: 1.25;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.prediction-comment-meta time {
    color: var(--muted);
    font-size: 13px;
    line-height: 1.25;
    white-space: nowrap;
}

.prediction-comment-author-badge {
    min-height: 20px;
    display: inline-flex;
    align-items: center;
    padding: 0 6px;
    border-radius: 5px;
    color: var(--ink);
    background: #9aa0a8;
    font-size: 10px;
    font-weight: 900;
    line-height: 1;
    text-transform: uppercase;
}

.prediction-comment-text {
    grid-column: 2 / -1;
    margin: 0;
    padding-right: 8px;
    color: rgba(255, 255, 255, .82);
    font-size: 15px;
    line-height: 1.55;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
}

.prediction-comment-delete {
    grid-column: 3;
    grid-row: 1;
    align-self: start;
    width: 32px;
    height: 32px;
    display: grid;
    place-items: center;
    padding: 0;
    border-radius: 8px;
    color: #8a919b;
    background: transparent;
    font-size: 0;
}

.prediction-comment-delete::before {
    content: "⋮";
    font-size: 24px;
    font-weight: 800;
    line-height: 1;
}

.prediction-comment-delete:hover {
    color: #fff;
    background: transparent;
}

.prediction-comment-delete:disabled {
    opacity: .55;
    cursor: wait;
}

.prediction-comments-empty {
    min-height: 300px;
    display: grid;
    place-items: center;
    align-content: center;
    gap: 6px;
    padding: 24px;
    border-radius: 14px;
    color: var(--muted);
    background: #252527;
    text-align: center;
}

.prediction-comments-empty strong {
    color: var(--text);
}

.prediction-comments-more {
    width: 100%;
    min-height: 52px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    justify-self: stretch;
    padding: 0 18px;
    border-radius: 10px;
    color: var(--text);
    background: #29292d;
    font-size: 14px;
    font-weight: 800;
}

.prediction-comments-more:hover {
    background: #343438;
}

.prediction-comments-more:disabled {
    opacity: .55;
    cursor: wait;
}

@media (max-width: 640px) {
    .prediction-comments {
        gap: 18px;
        padding: 18px;
        border-radius: 18px;
    }

    .prediction-comments-head {
        align-items: flex-start;
    }

    .prediction-comments-head h2 {
        font-size: 24px;
    }

    .prediction-comments-total {
        padding-top: 5px;
        font-size: 11px;
    }

    .prediction-comment-form {
        grid-template-columns: 44px minmax(0, 1fr);
        gap: 10px;
        min-height: 52px;
    }

    .prediction-comment-form .prediction-comment-avatar {
        width: 44px;
        height: 44px;
    }

    .prediction-comment-form textarea {
        height: 52px;
        min-height: 52px;
        padding: 15px 60px 15px 14px;
        font-size: 14px;
    }

    .prediction-comment-submit {
        top: 6px;
        right: 6px;
        width: 40px;
        height: 40px;
    }

    .prediction-comments-list,
    .prediction-comments-empty {
        min-height: 260px;
    }

    .prediction-comment {
        grid-template-columns: 46px minmax(0, 1fr) 28px;
        column-gap: 11px;
        padding: 15px 0 18px;
    }

    .prediction-comment > .prediction-comment-avatar {
        width: 46px;
        height: 46px;
    }

    .prediction-comment::after {
        left: 57px;
    }

    .prediction-comment-meta {
        gap: 5px 8px;
    }

    .prediction-comment-meta strong,
    .prediction-comment-text {
        font-size: 14px;
    }

    .prediction-comment-meta time {
        font-size: 12px;
    }

    .prediction-comment-delete {
        width: 28px;
        height: 28px;
    }

    .prediction-comment-text {
        padding-right: 0;
    }
}
'''
css = replace_once(
    css,
    r'/\* Prediction detail comments \*/.*?(?=\n\n/\* Consolidated former temp\.css overrides \*/)',
    css_replacement,
    label="prediction comments css block",
)
css_path.write_text(css, encoding="utf-8")


js_path = Path("front/static/front/js/comments.js")
js = js_path.read_text(encoding="utf-8")

required_replacements = [
    (
        '    const totalNode = root.querySelector("[data-comments-total]");\n',
        '    const totalNode = root.querySelector("[data-comments-total]");\n    const totalLabel = root.querySelector("[data-comments-total-label]");\n',
        "total label hook",
    ),
    (
        '    const predictionId = root.dataset.predictionId || "";\n',
        '    const predictionId = root.dataset.predictionId || "";\n    const authorId = root.dataset.authorId || "";\n',
        "author id hook",
    ),
    (
        '    let submitting = false;\n',
        '    let submitting = false;\n    let totalCount = Number.parseInt(totalNode?.textContent || "0", 10) || 0;\n',
        "initial total count",
    ),
    (
        '            image.width = 40;\n            image.height = 40;\n',
        '            image.width = 52;\n            image.height = 52;\n',
        "dynamic avatar dimensions",
    ),
]
for old, new, label in required_replacements:
    if old not in js:
        raise SystemExit(f"comments.js block not found: {label}")
    js = js.replace(old, new, 1)

counter_old = '''        if (totalNode) totalNode.textContent = String(safeCount);

        document.querySelectorAll("[data-comment-count]").forEach((node) => {'''
counter_new = '''        totalCount = safeCount;
        if (totalNode) totalNode.textContent = String(safeCount);
        if (totalLabel) {
            totalLabel.textContent = russianPlural(safeCount, "комментарий", "комментария", "комментариев");
        }

        document.querySelectorAll("[data-comment-count]").forEach((node) => {'''
if counter_old not in js:
    raise SystemExit("comments counter block not found")
js = js.replace(counter_old, counter_new, 1)

date_replacement = '''    const russianPlural = (value, one, few, many) => {
        const absolute = Math.abs(Number(value) || 0);
        const mod100 = absolute % 100;
        const mod10 = absolute % 10;
        if (mod100 >= 11 && mod100 <= 14) return many;
        if (mod10 === 1) return one;
        if (mod10 >= 2 && mod10 <= 4) return few;
        return many;
    };

    const formatDate = (value) => {
        if (!value) return "";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return "";

        const diffMs = Math.max(0, Date.now() - date.getTime());
        const minutes = Math.floor(diffMs / 60000);
        if (minutes < 1) return "только что";
        if (minutes < 60) {
            return `${minutes} ${russianPlural(minutes, "минуту", "минуты", "минут")} назад`;
        }

        const hours = Math.floor(minutes / 60);
        if (hours < 24) {
            return `${hours} ${russianPlural(hours, "час", "часа", "часов")} назад`;
        }

        const days = Math.floor(hours / 24);
        if (days < 7) {
            return `${days} ${russianPlural(days, "день", "дня", "дней")} назад`;
        }

        return new Intl.DateTimeFormat("ru-RU", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
        }).format(date);
    };

    const initialsFor'''
js = replace_once(
    js,
    r'    const formatDate = \(value\) => \{.*?\n    \};\n\n    const initialsFor',
    date_replacement,
    label="comments date formatter",
)

meta_old = '''        const author = document.createElement("strong");
        author.textContent = displayName;

        const time = document.createElement("time");
        time.dateTime = comment.created_at || "";
        time.textContent = formatDate(comment.created_at);

        meta.append(author, time);'''
meta_new = '''        const author = document.createElement("strong");
        author.textContent = displayName;

        const time = document.createElement("time");
        time.dateTime = comment.created_at || "";
        time.textContent = formatDate(comment.created_at);

        meta.append(author);
        if (String(comment.user?.id || "") === authorId) {
            const authorBadge = document.createElement("span");
            authorBadge.className = "prediction-comment-author-badge";
            authorBadge.textContent = "Автор";
            meta.append(authorBadge);
        }
        meta.append(time);'''
if meta_old not in js:
    raise SystemExit("comments author meta block not found")
js = js.replace(meta_old, meta_new, 1)

more_old = '''    const syncMoreButton = () => {
        if (!moreButton) return;
        moreButton.hidden = !previousPage;
        moreButton.disabled = loading;
    };'''
more_new = '''    const syncMoreButton = () => {
        if (!moreButton) return;
        moreButton.hidden = !previousPage;
        moreButton.disabled = loading;
        if (!previousPage) return;

        const shownCount = list?.querySelectorAll(".prediction-comment").length || 0;
        const remaining = Math.max(0, totalCount - shownCount);
        moreButton.textContent = `Показать ещё комментарии${remaining ? ` (${remaining})` : ""}`;
    };'''
if more_old not in js:
    raise SystemExit("comments more button block not found")
js = js.replace(more_old, more_new, 1)

init_old = '''    syncComposer();
    syncMoreButton();
})();'''
init_new = '''    updateCounters(totalCount);
    syncComposer();
    syncMoreButton();
})();'''
if init_old not in js:
    raise SystemExit("comments init block not found")
js = js.replace(init_old, init_new, 1)
js_path.write_text(js, encoding="utf-8")


comment_views_path = Path("front/comment_views.py")
comment_views = comment_views_path.read_text(encoding="utf-8")
if comment_views.count("COMMENTS_PAGE_SIZE = 20") != 1:
    raise SystemExit("unexpected COMMENTS_PAGE_SIZE source")
comment_views = comment_views.replace("COMMENTS_PAGE_SIZE = 20", "COMMENTS_PAGE_SIZE = 3", 1)
comment_views_path.write_text(comment_views, encoding="utf-8")


prediction_views_path = Path("front/prediction_views.py")
prediction_views = prediction_views_path.read_text(encoding="utf-8")
if prediction_views.count("comments_page_size = 20") != 1:
    raise SystemExit("unexpected prediction comments page size source")
prediction_views = prediction_views.replace("comments_page_size = 20", "comments_page_size = 3", 1)
prediction_views_path.write_text(prediction_views, encoding="utf-8")
