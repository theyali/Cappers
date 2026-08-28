from types import SimpleNamespace

from django.test import SimpleTestCase

from game.templatetags.match_ui import live_status_label


class LiveStatusLabelTests(SimpleTestCase):
    def match(self, *, time_status="", minute=None, label="", raw=None):
        return SimpleNamespace(
            time_status=time_status,
            live_minute=minute,
            live_minute_label=label,
            raw_data=raw or {},
        )

    def test_first_half(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", label="44")),
            "1Т - 44′",
        )

    def test_second_half(self):
        self.assertEqual(
            live_status_label(self.match(time_status="2", label="67'")),
            "2Т - 67′",
        )

    def test_stale_first_half_status_uses_live_minute(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", minute=90, label="90")),
            "2Т - 90′",
        )

    def test_second_half_stoppage_time_is_not_extra_time(self):
        self.assertEqual(
            live_status_label(self.match(time_status="1", label="90+4")),
            "2Т - 90+4′",
        )

    def test_extra_time(self):
        self.assertEqual(
            live_status_label(self.match(time_status="ET", minute=108)),
            "Extra 108′",
        )

    def test_halftime(self):
        self.assertEqual(
            live_status_label(self.match(time_status="HT", minute=45)),
            "Перерыв",
        )
