from pathlib import Path
from textwrap import dedent
import py_compile


def insert_before(path: str, marker: str, addition: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker not in text:
        raise SystemExit(f"Marker not found in {path}: {marker[:120]!r}")
    target.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")


models = Path("back/models.py")
text = models.read_text(encoding="utf-8")
if "match_detail_bookmaker_left = models.ForeignKey(" not in text:
    insert_before(
        "back/models.py",
        "    home_about_enabled = models.BooleanField(",
        '''    match_detail_bookmaker_left = models.ForeignKey(
        Bookmaker,
        verbose_name="Матч — БК слева",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    match_detail_bookmaker_right = models.ForeignKey(
        Bookmaker,
        verbose_name="Матч — БК справа",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    prediction_bookmaker_left = models.ForeignKey(
        Bookmaker,
        verbose_name="Прогнозы — БК 1",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    prediction_bookmaker_right = models.ForeignKey(
        Bookmaker,
        verbose_name="Прогнозы — БК 2",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

''',
    )


admin = Path("back/admin.py")
text = admin.read_text(encoding="utf-8")
if '"Букмекеры — страница матча"' not in text:
    insert_before(
        "back/admin.py",
        '''        (
            "Главная страница — О нас",
''',
        '''        (
            "Букмекеры — страница матча",
            {
                "fields": (
                    "match_detail_bookmaker_left",
                    "match_detail_bookmaker_right",
                ),
                "description": "Логотипы и ссылки по бокам от коэффициентов 1 / X / 2 в карточке матча.",
            },
        ),
        (
            "Букмекеры — прогнозы",
            {
                "fields": (
                    "prediction_bookmaker_left",
                    "prediction_bookmaker_right",
                ),
                "description": "Компактные ссылки на БК в карточках прогнозов и табличном режиме.",
            },
        ),
''',
    )


Path("back/migrations/0005_website_settings_bookmaker_placements.py").write_text(
    dedent('''\
        from django.db import migrations, models
        import django.db.models.deletion


        class Migration(migrations.Migration):
            dependencies = [
                ("back", "0004_bookmaker_home_fields"),
            ]

            operations = [
                migrations.AddField(
                    model_name="websitesettings",
                    name="match_detail_bookmaker_left",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="back.bookmaker",
                        verbose_name="Матч — БК слева",
                    ),
                ),
                migrations.AddField(
                    model_name="websitesettings",
                    name="match_detail_bookmaker_right",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="back.bookmaker",
                        verbose_name="Матч — БК справа",
                    ),
                ),
                migrations.AddField(
                    model_name="websitesettings",
                    name="prediction_bookmaker_left",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="back.bookmaker",
                        verbose_name="Прогнозы — БК 1",
                    ),
                ),
                migrations.AddField(
                    model_name="websitesettings",
                    name="prediction_bookmaker_right",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="back.bookmaker",
                        verbose_name="Прогнозы — БК 2",
                    ),
                ),
            ]
    '''),
    encoding="utf-8",
)


Path("templates/front/includes/_bookmaker_link.html").write_text(
    dedent('''\
        {% if bookmaker %}
        <a
            class="bookmaker-ref{% if variant == 'scoreboard' %} is-scoreboard{% else %} is-compact{% endif %}"
            href="{{ bookmaker.link }}"
            target="_blank"
            rel="nofollow sponsored noopener noreferrer"
            aria-label="Перейти в {{ bookmaker.name }}"
            title="{{ bookmaker.name }}"
        >
            <span class="bookmaker-ref-logo{% if bookmaker.icon %} has-image{% endif %}"{% if bookmaker.icon %} data-skeleton-image{% endif %}>
                {% if bookmaker.icon %}
                    {% if variant == 'scoreboard' %}
                        <img src="{{ bookmaker.icon.url }}" width="92" height="32" loading="lazy" alt="{{ bookmaker.name }}">
                    {% else %}
                        <img src="{{ bookmaker.icon.url }}" width="24" height="24" loading="lazy" alt="{{ bookmaker.name }}">
                    {% endif %}
                {% else %}
                    <strong>{{ bookmaker.name|slice:":2"|upper }}</strong>
                {% endif %}
            </span>
        </a>
        {% endif %}
    '''),
    encoding="utf-8",
)


match_template = Path("templates/game/match_detail.html")
text = match_template.read_text(encoding="utf-8")
if 'class="match-detail-bookmaker-strip"' not in text:
    old = '''                        {% if match.away_team_name_en %}<small>{{ match.away_team_name_en }}</small>{% endif %}
                    </div>
                </div>
            </article>
'''
    new = '''                        {% if match.away_team_name_en %}<small>{{ match.away_team_name_en }}</small>{% endif %}
                    </div>

                    {% if website_settings and match.coupon_odds.has_any %}
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
                </div>
            </article>
'''
    if old not in text:
        raise SystemExit("match_detail scoreboard marker not found")
    match_template.write_text(text.replace(old, new, 1), encoding="utf-8")


card = Path("templates/front/_prediction_card.html")
text = card.read_text(encoding="utf-8")
if 'class="prediction-bookmaker-links"' not in text:
    marker = '''        <div class="prediction-odd-value">
'''
    addition = '''        {% if website_settings.prediction_bookmaker_left or website_settings.prediction_bookmaker_right %}
        <div class="prediction-bookmaker-links" aria-label="Букмекеры">
            {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker_left variant="compact" only %}
            {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker_right variant="compact" only %}
        </div>
        {% endif %}
'''
    if marker not in text:
        raise SystemExit("prediction card odds marker not found")
    card.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")


table = Path("templates/front/includes/_prediction_table_view.html")
text = table.read_text(encoding="utf-8")
if 'class="prediction-bookmaker-links is-table"' not in text:
    marker = '''                        <div class="prediction-table-actions">
'''
    addition = '''                        <div class="prediction-table-actions">
                            {% if website_settings.prediction_bookmaker_left or website_settings.prediction_bookmaker_right %}
                            <div class="prediction-bookmaker-links is-table" aria-label="Букмекеры">
                                {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker_left variant="compact" only %}
                                {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.prediction_bookmaker_right variant="compact" only %}
                            </div>
                            {% endif %}
'''
    if marker not in text:
        raise SystemExit("prediction table actions marker not found")
    table.write_text(text.replace(marker, addition, 1), encoding="utf-8")


css = Path("front/static/front/css/main.css")
text = css.read_text(encoding="utf-8").rstrip()
if "/* Configurable bookmaker placements */" not in text:
    text += "\n\n" + dedent('''\
        /* Configurable bookmaker placements */
        .match-detail-scoreboard { flex-wrap: wrap; }
        .match-detail-bookmaker-strip {
            width: 100%;
            flex: 0 0 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 14px;
            margin-top: 4px;
        }
        .match-detail-featured-odds {
            display: grid;
            grid-template-columns: repeat(3, 86px);
            gap: 8px;
        }
        .match-detail-featured-odd {
            min-height: 62px;
            display: grid;
            place-items: center;
            align-content: center;
            gap: 2px;
            padding: 8px 10px;
            border-radius: 12px;
            color: #fff;
            background: var(--blue);
        }
        .match-detail-featured-odd small {
            color: rgba(255, 255, 255, .72);
            font-size: 12px;
            font-weight: 700;
        }
        .match-detail-featured-odd strong { font-size: 18px; line-height: 1; }
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
            width: 108px;
            height: 44px;
            padding: 6px 8px;
            border-radius: 999px;
        }
        .bookmaker-ref.is-scoreboard img {
            width: 92px;
            height: 32px;
            display: block;
            object-fit: contain;
        }
        .bookmaker-ref.is-compact .bookmaker-ref-logo {
            width: 30px;
            height: 30px;
            padding: 3px;
            border-radius: 8px;
        }
        .bookmaker-ref.is-compact img {
            width: 24px;
            height: 24px;
            display: block;
            object-fit: contain;
        }
        .bookmaker-ref-logo > strong { font-size: 10px; font-weight: 800; }
        .prediction-bookmaker-links {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            margin-left: auto;
        }
        .prediction-bookmaker-links.is-table { margin-left: 0; margin-right: 2px; }
        .prediction-table-actions { gap: 5px; }
        @media (max-width: 760px) {
            .match-detail-bookmaker-strip { gap: 8px; }
            .match-detail-featured-odds {
                grid-template-columns: repeat(3, minmax(64px, 1fr));
                flex: 1 1 auto;
            }
            .match-detail-featured-odd { min-height: 54px; padding: 7px 5px; }
            .bookmaker-ref.is-scoreboard .bookmaker-ref-logo {
                width: 58px;
                height: 40px;
                padding: 5px;
                border-radius: 10px;
            }
            .bookmaker-ref.is-scoreboard img { width: 48px; height: 28px; }
            .prediction-bookmaker-links .bookmaker-ref:nth-child(2) { display: none; }
        }
    ''') + "\n"
    css.write_text(text, encoding="utf-8")


for path in (
    "back/models.py",
    "back/admin.py",
    "back/migrations/0005_website_settings_bookmaker_placements.py",
):
    py_compile.compile(path, doraise=True)
