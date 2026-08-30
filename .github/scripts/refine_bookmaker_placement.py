from pathlib import Path
import py_compile


def replace_between(path: str, start_marker: str, end_marker: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    start = text.find(start_marker)
    if start == -1:
        raise SystemExit(f"Start marker not found in {path}: {start_marker!r}")
    end = text.find(end_marker, start)
    if end == -1:
        raise SystemExit(f"End marker not found in {path}: {end_marker!r}")
    target.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


# 1. WebsiteSettings: keep one bookmaker for match UI and one for predictions.
models = Path("back/models.py")
text = models.read_text(encoding="utf-8")
start = "    match_detail_bookmaker_left = models.ForeignKey(\n"
end = "    home_about_enabled = models.BooleanField("
replacement = '''    match_bookmaker = models.ForeignKey(
        Bookmaker,
        verbose_name="Матч — БК",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    prediction_bookmaker = models.ForeignKey(
        Bookmaker,
        verbose_name="Прогнозы — БК",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

'''
if "match_detail_bookmaker_left = models.ForeignKey(" in text:
    s = text.index(start)
    e = text.index(end, s)
    models.write_text(text[:s] + replacement + text[e:], encoding="utf-8")


# 2. Admin: one clean bookmaker section with two selectors.
admin = Path("back/admin.py")
text = admin.read_text(encoding="utf-8")
start = '        (\n            "Букмекеры — страница матча",\n'
end = '        (\n            "Главная страница — О нас",\n'
replacement = '''        (
            "Букмекеры",
            {
                "fields": (
                    "match_bookmaker",
                    "prediction_bookmaker",
                ),
                "description": "Отдельный букмекер для коэффициентов матчей и отдельный — для карточек прогнозов.",
            },
        ),
'''
if '"Букмекеры — страница матча"' in text:
    s = text.index(start)
    e = text.index(end, s)
    admin.write_text(text[:s] + replacement + text[e:], encoding="utf-8")


# 3. Data-safe migration: if only the former right field was filled, copy it first.
migration = Path("back/migrations/0006_simplify_bookmaker_placements.py")
migration.write_text('''from django.db import migrations


def keep_existing_bookmaker_choices(apps, schema_editor):
    WebsiteSettings = apps.get_model("back", "WebsiteSettings")
    for settings in WebsiteSettings.objects.all():
        fields = []
        if not settings.match_detail_bookmaker_left_id and settings.match_detail_bookmaker_right_id:
            settings.match_detail_bookmaker_left_id = settings.match_detail_bookmaker_right_id
            fields.append("match_detail_bookmaker_left")
        if not settings.prediction_bookmaker_left_id and settings.prediction_bookmaker_right_id:
            settings.prediction_bookmaker_left_id = settings.prediction_bookmaker_right_id
            fields.append("prediction_bookmaker_left")
        if fields:
            settings.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0005_website_settings_bookmaker_placements"),
    ]

    operations = [
        migrations.RunPython(keep_existing_bookmaker_choices, migrations.RunPython.noop),
        migrations.RenameField(
            model_name="websitesettings",
            old_name="match_detail_bookmaker_left",
            new_name="match_bookmaker",
        ),
        migrations.RemoveField(
            model_name="websitesettings",
            name="match_detail_bookmaker_right",
        ),
        migrations.RenameField(
            model_name="websitesettings",
            old_name="prediction_bookmaker_left",
            new_name="prediction_bookmaker",
        ),
        migrations.RemoveField(
            model_name="websitesettings",
            name="prediction_bookmaker_right",
        ),
    ]
''', encoding="utf-8")


# 4. Match detail: one bookmaker + three main coefficients.
match_detail = Path("templates/game/match_detail.html")
text = match_detail.read_text(encoding="utf-8")
old = '''                    {% if website_settings and match.coupon_odds.has_any %}
                    <div class="match-detail-bookmaker-strip" aria-label="Коэффициенты и букмекеры">
                        {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_detail_bookmaker_left variant="scoreboard" only %}
                        <div class="match-detail-featured-odds" aria-label="Основные коэффициенты 1 X 2">
                            <span class="match-detail-featured-odd"><small>1</small><strong>{% if match.coupon_odds.home %}{{ match.coupon_odds.home|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                            <span class="match-detail-featured-odd"><small>X</small><strong>{% if match.coupon_odds.draw %}{{ match.coupon_odds.draw|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                            <span class="match-detail-featured-odd"><small>2</small><strong>{% if match.coupon_odds.away %}{{ match.coupon_odds.away|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                        </div>
                        {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_detail_bookmaker_right variant="scoreboard" only %}
                    </div>
                    {% endif %}
'''
new = '''                    {% if website_settings and match.coupon_odds.has_any %}
                    <div class="match-detail-bookmaker-strip" aria-label="Коэффициенты и букмекер">
                        {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_bookmaker variant="scoreboard" only %}
                        <div class="match-detail-featured-odds" aria-label="Основные коэффициенты 1 X 2">
                            <span class="match-detail-featured-odd"><small>1</small><strong>{% if match.coupon_odds.home %}{{ match.coupon_odds.home|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                            <span class="match-detail-featured-odd"><small>X</small><strong>{% if match.coupon_odds.draw %}{{ match.coupon_odds.draw|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                            <span class="match-detail-featured-odd"><small>2</small><strong>{% if match.coupon_odds.away %}{{ match.coupon_odds.away|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                        </div>
                    </div>
                    {% endif %}
'''
if old not in text:
    raise SystemExit("match_detail bookmaker block not found")
match_detail.write_text(text.replace(old, new, 1), encoding="utf-8")


# 5. Prediction rich card: a single compact bookmaker icon.
card = Path("templates/front/_prediction_card.html")
text = card.read_text(encoding="utf-8")
old = '''        {% if website_settings.prediction_bookmaker_left or website_settings.prediction_bookmaker_right %}
        <div class="prediction-bookmaker-links" aria-label="Букмекеры">
            {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker_left variant="compact" only %}
            {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker_right variant="compact" only %}
        </div>
        {% endif %}
'''
new = '''        {% if website_settings.prediction_bookmaker %}
        <div class="prediction-bookmaker-links" aria-label="Букмекер">
            {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker variant="compact" only %}
        </div>
        {% endif %}
'''
if old not in text:
    raise SystemExit("prediction card bookmaker block not found")
card.write_text(text.replace(old, new, 1), encoding="utf-8")


# 6. Prediction table: a single icon in the actions cell.
table = Path("templates/front/includes/_prediction_table_view.html")
text = table.read_text(encoding="utf-8")
old = '''                            {% if website_settings.prediction_bookmaker_left or website_settings.prediction_bookmaker_right %}
                            <div class="prediction-bookmaker-links is-table" aria-label="Букмекеры">
                                {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker_left variant="compact" only %}
                                {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker_right variant="compact" only %}
                            </div>
                            {% endif %}
'''
new = '''                            {% if website_settings.prediction_bookmaker %}
                            <div class="prediction-bookmaker-links is-table" aria-label="Букмекер">
                                {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker variant="compact" only %}
                            </div>
                            {% endif %}
'''
if old not in text:
    raise SystemExit("prediction table bookmaker block not found")
table.write_text(text.replace(old, new, 1), encoding="utf-8")


# 7. Match cards, including home page: show the selected match bookmaker once next to the odds row.
match_card = Path("templates/game/includes/_match_card.html")
text = match_card.read_text(encoding="utf-8")
open_marker = '''    <div
        class="coupon-options match-card-options'''
if "match-card-odds-row" not in text:
    idx = text.find(open_marker)
    if idx == -1:
        raise SystemExit("match card coupon options marker not found")
    prefix = '''    <div class="match-card-odds-row{% if not website_settings.match_bookmaker %} without-bookmaker{% endif %}">
        {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_bookmaker variant="compact" only %}
'''
    text = text[:idx] + prefix + text[idx:]
    tail = "    </div>\n</article>\n"
    pos = text.rfind(tail)
    if pos == -1:
        raise SystemExit("match card closing marker not found")
    text = text[:pos] + "    </div>\n    </div>\n</article>\n" + text[pos + len(tail):]
    match_card.write_text(text, encoding="utf-8")


# 8. Replace our previous CSS block at EOF with the refined layout.
css = Path("front/static/front/css/main.css")
text = css.read_text(encoding="utf-8")
marker = "/* Configurable bookmaker placements */"
idx = text.find(marker)
if idx == -1:
    raise SystemExit("bookmaker CSS marker not found")
css_block = r'''/* Configurable bookmaker placements */
.match-detail-scoreboard {
    flex-wrap: wrap;
}

.match-detail-bookmaker-strip {
    width: 100%;
    flex: 0 0 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    margin-top: 4px;
}

.match-detail-featured-odds {
    display: grid;
    grid-template-columns: repeat(3, 82px);
    gap: 7px;
}

.match-detail-featured-odd {
    min-height: 58px;
    display: grid;
    place-items: center;
    align-content: center;
    gap: 2px;
    padding: 7px 9px;
    border-radius: 11px;
    color: #fff;
    background: var(--blue);
}

.match-detail-featured-odd small {
    color: rgba(255, 255, 255, .72);
    font-size: 12px;
    font-weight: 700;
}

.match-detail-featured-odd strong {
    font-size: 18px;
    line-height: 1;
}

.bookmaker-ref {
    flex: 0 0 auto;
    display: inline-grid;
    place-items: center;
    text-decoration: none;
}

.bookmaker-ref-logo {
    display: grid;
    place-items: center;
    overflow: hidden;
    color: var(--ink);
    background: #fff;
}

.bookmaker-ref.is-scoreboard .bookmaker-ref-logo {
    width: 88px;
    height: 40px;
    padding: 5px 7px;
    border-radius: 999px;
}

.bookmaker-ref.is-scoreboard img {
    width: 74px;
    height: 28px;
    display: block;
    object-fit: contain;
}

.bookmaker-ref.is-compact .bookmaker-ref-logo {
    width: 32px;
    height: 32px;
    padding: 3px;
    border-radius: 8px;
}

.bookmaker-ref.is-compact img {
    width: 26px;
    height: 26px;
    display: block;
    object-fit: contain;
}

.bookmaker-ref-logo > strong {
    font-size: 10px;
    font-weight: 800;
}

.prediction-pick-rich {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    align-items: center;
    gap: 10px;
}

.prediction-bookmaker-links {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin: 0;
}

.prediction-bookmaker-links.is-table {
    margin: 0 2px 0 0;
}

.prediction-table-actions {
    display: flex;
    align-items: center;
    gap: 5px;
}

.match-card-odds-row {
    display: grid;
    grid-template-columns: 32px minmax(0, 1fr);
    align-items: stretch;
    gap: 7px;
}

.match-card-odds-row.without-bookmaker {
    grid-template-columns: minmax(0, 1fr);
}

.match-card-odds-row > .bookmaker-ref {
    align-self: stretch;
}

.match-card-odds-row > .bookmaker-ref .bookmaker-ref-logo {
    width: 32px;
    height: 100%;
    min-height: 44px;
    border-radius: 8px;
}

.match-card-odds-row > .bookmaker-ref img {
    width: 26px;
    height: 26px;
}

.match-card-odds-row .match-card-options {
    min-width: 0;
}

@media (max-width: 760px) {
    .match-detail-bookmaker-strip {
        gap: 7px;
    }

    .match-detail-featured-odds {
        flex: 1 1 auto;
        grid-template-columns: repeat(3, minmax(52px, 1fr));
        max-width: 244px;
    }

    .match-detail-featured-odd {
        min-height: 52px;
        padding: 6px 4px;
    }

    .bookmaker-ref.is-scoreboard .bookmaker-ref-logo {
        width: 56px;
        height: 38px;
        padding: 4px;
        border-radius: 9px;
    }

    .bookmaker-ref.is-scoreboard img {
        width: 48px;
        height: 28px;
    }

    .prediction-pick-rich {
        grid-template-columns: minmax(0, 1fr) 32px auto;
        gap: 7px;
    }
}
'''
css.write_text(text[:idx].rstrip() + "\n\n" + css_block, encoding="utf-8")


# Validate Python files and make sure old field references are gone from active code/templates.
for path in (
    "back/models.py",
    "back/admin.py",
    "back/migrations/0006_simplify_bookmaker_placements.py",
):
    py_compile.compile(path, doraise=True)

for path in (
    "back/models.py",
    "back/admin.py",
    "templates/game/match_detail.html",
    "templates/front/_prediction_card.html",
    "templates/front/includes/_prediction_table_view.html",
    "templates/game/includes/_match_card.html",
):
    active = Path(path).read_text(encoding="utf-8")
    for stale in (
        "match_detail_bookmaker_left",
        "match_detail_bookmaker_right",
        "prediction_bookmaker_left",
        "prediction_bookmaker_right",
    ):
        if stale in active:
            raise SystemExit(f"Stale field {stale} remains in {path}")

print("Bookmaker placement refinement applied successfully")
