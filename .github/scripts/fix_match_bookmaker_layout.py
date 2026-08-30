from pathlib import Path


# Match cards: bookmaker is a separate compact row above coupon options.
match_card = Path("templates/game/includes/_match_card.html")
text = match_card.read_text(encoding="utf-8")
old = '''    <div class="match-card-odds-row{% if not website_settings.match_bookmaker %} without-bookmaker{% endif %}">
        {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_bookmaker variant="compact" only %}
    <div
        class="coupon-options match-card-options'''
new = '''    <div class="match-card-odds-row{% if not website_settings.match_bookmaker %} without-bookmaker{% endif %}">
        {% if website_settings.match_bookmaker %}
        <div class="match-card-bookmaker-row" aria-label="Букмекер матча">
            {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_bookmaker variant="compact" only %}
        </div>
        {% endif %}
        <div
        class="coupon-options match-card-options'''
if old not in text:
    raise SystemExit("match card bookmaker marker not found")
match_card.write_text(text.replace(old, new, 1), encoding="utf-8")


# Match detail: same configured bookmaker on both sides, odds exactly centered.
match_detail = Path("templates/game/match_detail.html")
text = match_detail.read_text(encoding="utf-8")
old = '''                    <div class="match-detail-bookmaker-strip" aria-label="Коэффициенты и букмекер">
                        {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_bookmaker variant="scoreboard" only %}
                        <div class="match-detail-featured-odds" aria-label="Основные коэффициенты 1 X 2">
                            <span class="match-detail-featured-odd"><small>1</small><strong>{% if match.coupon_odds.home %}{{ match.coupon_odds.home|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                            <span class="match-detail-featured-odd"><small>X</small><strong>{% if match.coupon_odds.draw %}{{ match.coupon_odds.draw|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                            <span class="match-detail-featured-odd"><small>2</small><strong>{% if match.coupon_odds.away %}{{ match.coupon_odds.away|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                        </div>
                    </div>'''
new = '''                    <div class="match-detail-bookmaker-strip{% if not website_settings.match_bookmaker %} without-bookmaker{% endif %}" aria-label="Коэффициенты и букмекер">
                        {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_bookmaker variant="scoreboard" only %}
                        <div class="match-detail-featured-odds" aria-label="Основные коэффициенты 1 X 2">
                            <span class="match-detail-featured-odd"><small>1</small><strong>{% if match.coupon_odds.home %}{{ match.coupon_odds.home|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                            <span class="match-detail-featured-odd"><small>X</small><strong>{% if match.coupon_odds.draw %}{{ match.coupon_odds.draw|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                            <span class="match-detail-featured-odd"><small>2</small><strong>{% if match.coupon_odds.away %}{{ match.coupon_odds.away|floatformat:2 }}{% else %}—{% endif %}</strong></span>
                        </div>
                        {% include "front/includes/_bookmaker_link.html" with bookmaker=website_settings.match_bookmaker variant="scoreboard" only %}
                    </div>'''
if old not in text:
    raise SystemExit("match detail bookmaker marker not found")
match_detail.write_text(text.replace(old, new, 1), encoding="utf-8")


# Append final overrides in main.css only. No additional stylesheet.
css = Path("front/static/front/css/main.css")
text = css.read_text(encoding="utf-8").rstrip()
marker = "/* Match bookmaker layout correction */"
block = r'''
/* Match bookmaker layout correction */
.match-detail-scoreboard > .match-detail-bookmaker-strip {
    width: 100%;
    flex: 0 0 100%;
    align-self: stretch;
    display: grid;
    grid-template-columns: 88px auto 88px;
    align-items: center;
    justify-content: center;
    gap: 14px;
    margin: 12px 0 0;
}

.match-detail-bookmaker-strip.without-bookmaker {
    grid-template-columns: auto;
}

.match-detail-bookmaker-strip > .bookmaker-ref:first-child {
    justify-self: end;
}

.match-detail-bookmaker-strip > .bookmaker-ref:last-child {
    justify-self: start;
}

.match-detail-bookmaker-strip > .match-detail-featured-odds {
    justify-self: center;
}

.match-watch-card-shell .match-card-odds-row,
.match-card .match-card-odds-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
    gap: 7px;
}

.match-card-odds-row > .match-card-bookmaker-row {
    min-height: 32px;
    display: flex;
    align-items: center;
    justify-content: flex-start;
}

.match-card-odds-row > .match-card-bookmaker-row .bookmaker-ref {
    align-self: auto;
}

.match-card-odds-row > .match-card-bookmaker-row .bookmaker-ref-logo {
    width: 44px;
    height: 32px;
    min-height: 0;
    padding: 3px 5px;
    border-radius: 8px;
}

.match-card-odds-row > .match-card-bookmaker-row .bookmaker-ref img {
    width: 34px;
    height: 24px;
    object-fit: contain;
}

.match-card-odds-row .match-card-options {
    width: 100%;
    min-width: 0;
}

@media (max-width: 760px) {
    .match-detail-scoreboard > .match-detail-bookmaker-strip {
        grid-template-columns: 62px minmax(0, 1fr) 62px;
        gap: 7px;
        margin-top: 10px;
    }

    .match-detail-scoreboard > .match-detail-bookmaker-strip.without-bookmaker {
        grid-template-columns: minmax(0, 1fr);
    }

    .match-detail-bookmaker-strip > .match-detail-featured-odds {
        width: 100%;
        min-width: 0;
        grid-template-columns: repeat(3, minmax(54px, 1fr));
    }

    .match-watch-card-shell .match-card-odds-row,
    .match-card .match-card-odds-row {
        grid-template-columns: minmax(0, 1fr);
        gap: 6px;
    }
}
'''.strip()
if marker in text:
    text = text[:text.index(marker)].rstrip()
css.write_text(text + "\n\n" + block + "\n", encoding="utf-8")


# Static sanity checks.
card_text = match_card.read_text(encoding="utf-8")
detail_text = match_detail.read_text(encoding="utf-8")
assert 'class="match-card-bookmaker-row"' in card_text
assert card_text.index('class="match-card-bookmaker-row"') < card_text.index('class="coupon-options match-card-options')
assert detail_text.count('with bookmaker=website_settings.match_bookmaker variant="scoreboard" only') >= 2
assert 'grid-template-columns: 88px auto 88px;' in css.read_text(encoding="utf-8")
