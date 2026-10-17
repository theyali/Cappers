from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from game.templatetags.match_ui import live_status_label


class LiveStatusLabelTests(SimpleTestCase):
    def match(self, *, time_status="", minute=None, label="", raw=None, sport_code="football"):
        return SimpleNamespace(
            time_status=time_status,
            live_minute=minute,
            live_minute_label=label,
            raw_data=raw or {},
            sport_code=sport_code,
        )

    def test_first_half_uses_minute_not_time_status(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", label="44")),
            "1Т - 44′",
        )

    def test_second_half_uses_minute_not_time_status(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", label="67'")),
            "2Т - 67′",
        )

    def test_numeric_time_status_does_not_force_second_half(self):
        self.assertEqual(
            live_status_label(self.match(time_status="2", label="20")),
            "1Т - 20′",
        )

    def test_ninetieth_minute_is_second_half(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", minute=90, label="90")),
            "2Т - 90′",
        )

    def test_second_half_stoppage_time_is_not_extra_time(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", label="90+4")),
            "2Т - 90+4′",
        )

    def test_extra_time_uses_explicit_phase(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", minute=108, raw={"phase": "ET"})),
            "Extra 108′",
        )

    def test_halftime_uses_explicit_phase(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", minute=45, raw={"phase": "HT"})),
            "Перерыв",
        )

    def test_basketball_uses_quarter_label(self):
        self.assertEqual(
            live_status_label(self.match(sport_code="basketball", minute=18)),
            "2-я четверть - 18′",
        )

    def test_hockey_uses_period_label(self):
        self.assertEqual(
            live_status_label(self.match(sport_code="hockey", minute=43)),
            "3-й период - 43′",
        )

    def test_tennis_uses_set_label(self):
        self.assertEqual(
            live_status_label(self.match(sport_code="tennis", label="2")),
            "2-й сет",
        )


@override_settings(STORAGES={
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class MatchOddsGroupMarkupTests(SimpleTestCase):
    def render_group(self, *, count=16, can_write_coupon=False, scope="prematch", bettable=True):
        return render_to_string("game/_match_v2_odds_group.html", {
            "group": {
                "title": "Фора",
                "odds": [{
                    "market": "handicap", "selection": f"Home ({index - 8:+})",
                    "outcome_code": f"H{index}", "coefficient": "1.85",
                    "key": f"handicap-{index}", "label": f"Ф1 ({index - 8:+})",
                    "description": f"Хозяева с форой {index - 8:+}", "bettable": bettable,
                } for index in range(count)],
            },
            "match": SimpleNamespace(sync_scope=scope),
            "can_write_coupon": can_write_coupon,
        })

    def test_long_locked_row_remains_keyboard_scrollable_and_keeps_every_outcome(self):
        html = self.render_group()
        self.assertIn('class="match-v2-odds-grid" tabindex="0" role="region"', html)
        self.assertIn('aria-label="Фора — коэффициенты"', html)
        self.assertEqual(html.count('class="match-v2-odd odds-button"'), 16)
        self.assertEqual(html.count('aria-disabled="true"'), 16)
        self.assertNotIn("data-bet-option", html)
        self.assertIn("Хозяева с форой -8", html)
        self.assertIn("Хозяева с форой +7", html)

    def test_available_outcomes_keep_existing_coupon_attributes(self):
        html = self.render_group(count=3, can_write_coupon=True)
        self.assertEqual(html.count("data-bet-option"), 3)
        self.assertEqual(html.count("data-bet-key="), 3)
        self.assertEqual(html.count("data-outcome-code="), 3)
        self.assertNotIn('aria-disabled="true"', html)

    def test_suspended_and_non_prematch_rows_stay_locked(self):
        for scope, bettable in (("live", True), ("finished", True), ("prematch", False)):
            with self.subTest(scope=scope, bettable=bettable):
                html = self.render_group(count=2, can_write_coupon=True, scope=scope, bettable=bettable)
                self.assertEqual(html.count('aria-disabled="true"'), 2)
                self.assertNotIn("data-bet-option", html)
