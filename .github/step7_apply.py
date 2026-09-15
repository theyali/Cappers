from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise SystemExit(f"Expected block not found in {path}")
    file_path.write_text(text.replace(old, new), encoding="utf-8")


include_path = Path("templates/front/includes/_comment_metric.html")
include_path.write_text(
    '''<a\n    class="prediction-comment-metric{% if metric_class %} {{ metric_class }}{% endif %}"\n    href="{% url 'front:prediction_detail' prediction_id=prediction_id %}"\n    aria-label="Открыть прогноз и комментарии, комментариев: {{ comments_count|default:0 }}"\n    title="Комментарии"\n>\n    {% include "front/svgs/comment.svg" %}\n    <span>{{ comments_count|default:0 }}</span>\n</a>\n''',
    encoding="utf-8",
)

svg_path = Path("templates/front/svgs/comment.svg")
svg_path.write_text(
    '''<svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">\n    <path d="M5.5 18.2 3.8 21l3.8-1.1c1.3.7 2.8 1.1 4.4 1.1 5 0 9-3.6 9-8s-4-8-9-8-9 3.6-9 8c0 2 .9 3.8 2.5 5.2Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>\n</svg>\n''',
    encoding="utf-8",
)

replace_once(
    "templates/front/_prediction_card.html",
    '''            <span class="prediction-reaction-label">В избранное</span>\n        </button>\n    </div>\n\n    <div class="prediction-published-at">''',
    '''            <span class="prediction-reaction-label">В избранное</span>\n        </button>\n        {% include "front/includes/_comment_metric.html" with prediction_id=prediction.coupon.id comments_count=prediction.comments_count metric_class="prediction-reaction" only %}\n    </div>\n\n    <div class="prediction-published-at">''',
)

replace_once(
    "templates/front/includes/_feed_prediction_card.html",
    '''        <a class="feed-prediction-action feed-prediction-menu" href="{% url 'front:prediction_detail' prediction_id=prediction.coupon.id %}" aria-label="Открыть прогноз">\n            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 7.5h.01M12 12h.01M12 16.5h.01"></path></svg>\n        </a>''',
    '''        {% include "front/includes/_comment_metric.html" with prediction_id=prediction.coupon.id comments_count=prediction.comments_count metric_class="feed-prediction-action feed-prediction-comments" only %}''',
)

replace_once(
    "templates/front/includes/_prediction_table_row.html",
    '''            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 5.9c-1.8-2-4.8-2.1-6.8-.2L12 7.6l-2-1.9C8 3.8 5 3.9 3.2 5.9c-1.8 2-1.6 5 .4 6.9L12 20l8.4-7.2c2-1.9 2.2-4.9.4-6.9Z"></path></svg>\n        </button>\n    </div>\n</article>''',
    '''            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 5.9c-1.8-2-4.8-2.1-6.8-.2L12 7.6l-2-1.9C8 3.8 5 3.9 3.2 5.9c-1.8 2-1.6 5 .4 6.9L12 20l8.4-7.2c2-1.9 2.2-4.9.4-6.9Z"></path></svg>\n        </button>\n        {% include "front/includes/_comment_metric.html" with prediction_id=prediction.coupon.id comments_count=prediction.comments_count metric_class="prediction-table-action" only %}\n    </div>\n</article>''',
)

replace_all(
    "front/static/front/css/main.css",
    '''    .prediction-reactions {\n        display: grid;\n        grid-template-columns: 1fr 1fr;\n    }''',
    '''    .prediction-reactions {\n        display: grid;\n        grid-template-columns: repeat(3, minmax(0, 1fr));\n    }''',
)

css_path = Path("front/static/front/css/main.css")
css = css_path.read_text(encoding="utf-8")
marker = "/* Prediction comment metric */"
if marker in css:
    raise SystemExit("Prediction comment metric styles already exist")
css_path.write_text(
    css.rstrip()
    + '''\n\n\n/* Prediction comment metric */\n.prediction-comment-metric {\n    text-decoration: none;\n}\n\n.prediction-comment-metric > span {\n    font-size: 12px;\n    font-weight: 700;\n    line-height: 1;\n}\n\n.prediction-table-action.prediction-comment-metric {\n    width: auto;\n    min-width: 44px;\n    grid-template-columns: auto auto;\n    gap: 4px;\n    padding: 0 7px;\n}\n''',
    encoding="utf-8",
)

# Source-level guarantees for the shared UI contract.
for path in (
    "templates/front/_prediction_card.html",
    "templates/front/includes/_feed_prediction_card.html",
    "templates/front/includes/_prediction_table_row.html",
):
    text = Path(path).read_text(encoding="utf-8")
    if text.count('front/includes/_comment_metric.html') != 1:
        raise SystemExit(f"Expected exactly one comment metric include in {path}")

if Path("templates/front/svgs/comment.svg").read_text(encoding="utf-8").count("<svg") != 1:
    raise SystemExit("Comment SVG must be defined once")
