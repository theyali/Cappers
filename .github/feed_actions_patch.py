from pathlib import Path


template_path = Path("templates/front/includes/_feed_prediction_card.html")
css_path = Path("front/static/front/css/main.css")

template = template_path.read_text(encoding="utf-8")
old_actions = '''        <button
            class="feed-prediction-action feed-prediction-save prediction-favorite{% if prediction.is_favorite %} is-active{% endif %}"
            type="button"
            data-prediction-reaction
            data-authenticated="{% if request.user.is_authenticated %}true{% else %}false{% endif %}"
            data-url="{% url 'front:prediction_favorite' prediction_id=prediction.coupon.id %}"
            data-login-url="{% url 'cabinet:login' %}?next={{ request.get_full_path|urlencode }}"
            aria-pressed="{% if prediction.is_favorite %}true{% else %}false{% endif %}"
            {% if prediction.is_own %}disabled aria-disabled="true"{% endif %}
            title="{% if prediction.is_own %}Нельзя сохранять свой прогноз{% elif prediction.is_favorite %}Убрать из избранного{% else %}Добавить в избранное{% endif %}"
        >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 4.75A1.75 1.75 0 0 1 8.25 3h7.5a1.75 1.75 0 0 1 1.75 1.75v15L12 16.6l-5.5 3.15v-15Z"></path></svg>
        </button>

        {% include "front/includes/_comment_metric.html" with prediction_id=prediction.coupon.id comments_count=prediction.comments_count metric_class="feed-prediction-action feed-prediction-comments" only %}
'''
new_actions = '''        {% include "front/includes/_comment_metric.html" with prediction_id=prediction.coupon.id comments_count=prediction.comments_count metric_class="feed-prediction-action feed-prediction-comments" only %}

        <button
            class="feed-prediction-action feed-prediction-save prediction-favorite{% if prediction.is_favorite %} is-active{% endif %}"
            type="button"
            data-prediction-reaction
            data-authenticated="{% if request.user.is_authenticated %}true{% else %}false{% endif %}"
            data-url="{% url 'front:prediction_favorite' prediction_id=prediction.coupon.id %}"
            data-login-url="{% url 'cabinet:login' %}?next={{ request.get_full_path|urlencode }}"
            aria-pressed="{% if prediction.is_favorite %}true{% else %}false{% endif %}"
            {% if prediction.is_own %}disabled aria-disabled="true"{% endif %}
            title="{% if prediction.is_own %}Нельзя сохранять свой прогноз{% elif prediction.is_favorite %}Убрать из избранного{% else %}Добавить в избранное{% endif %}"
        >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 4.75A1.75 1.75 0 0 1 8.25 3h7.5a1.75 1.75 0 0 1 1.75 1.75v15L12 16.6l-5.5 3.15v-15Z"></path></svg>
        </button>

        <a
            class="feed-prediction-action feed-prediction-menu"
            href="{% url 'front:prediction_detail' prediction_id=prediction.coupon.id %}"
            aria-label="Открыть дополнительные действия прогноза"
            title="Открыть прогноз"
        >
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="5" r="1.7" fill="currentColor" stroke="none"></circle>
                <circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none"></circle>
                <circle cx="12" cy="19" r="1.7" fill="currentColor" stroke="none"></circle>
            </svg>
        </a>
'''
if old_actions not in template:
    raise SystemExit("feed actions template block not found")
template_path.write_text(template.replace(old_actions, new_actions, 1), encoding="utf-8")

css = css_path.read_text(encoding="utf-8")
old_layout = '''.feed-prediction-actions {
    display: grid;
    grid-template-columns: max-content max-content max-content;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    color: var(--muted);
}
'''
new_layout = '''.feed-prediction-actions {
    min-height: 38px;
    display: flex;
    align-items: center;
    gap: 22px;
    color: var(--muted);
}
'''
if old_layout not in css:
    raise SystemExit("feed actions css block not found")
css = css.replace(old_layout, new_layout, 1)

old_save = '''.feed-prediction-save.is-active {
    color: var(--yellow);
    background: transparent;
}

.feed-prediction-menu {
    padding-right: 0;
}
'''
new_save = '''.feed-prediction-save {
    margin-left: auto;
}

.feed-prediction-save.is-active {
    color: var(--yellow);
    background: transparent;
}

.feed-prediction-comments > span {
    font-size: 14px;
    font-weight: 600;
}

.feed-prediction-menu {
    padding-right: 0;
    padding-left: 0;
}
'''
if old_save not in css:
    raise SystemExit("feed save/menu css block not found")
css_path.write_text(css.replace(old_save, new_save, 1), encoding="utf-8")
