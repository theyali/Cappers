from types import SimpleNamespace

from django.test import SimpleTestCase

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
