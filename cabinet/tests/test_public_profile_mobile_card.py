from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings


@override_settings(STORAGES={
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class PublicProfileMobileCardTests(SimpleTestCase):
    def setUp(self):
        self.context = {
            "public_user": SimpleNamespace(
                username="public-reader", avatar=None, country=None, gender="",
                date_joined=datetime(2026, 10, 17, tzinfo=timezone.utc),
            ),
            "public_name": "Обычный пользователь",
            "public_initials": "ОП",
            "public_is_capper": False,
            "achievement_unlocked_count": 5,
            "achievement_total": 9,
            # Reader rendering must not depend on the presence of expert-only data.
            "analyst_profile": SimpleNamespace(trust_index=Decimal("8.8"), is_verified=True),
            "followers_count": 123,
            "predictions_count": 42,
            "win_rate": Decimal("65.5"),
            "profile_presence": SimpleNamespace(is_online=True),
            "leader_badges_more_count": 4,
        }

    def render(self):
        return render_to_string("cabinet/includes/_public_profile_mobile_card.html", self.context)

    def test_reader_has_shared_cover_and_own_metrics_only(self):
        html = self.render()
        self.assertIn('class="expert-mobile-card-bg"', html)
        self.assertIn('src="/static/front/img/profile_default_cover.png"', html)
        self.assertIn('<h1 class="expert-mobile-name">Обычный пользователь</h1>', html)
        self.assertIn("ОП", html)
        self.assertIn("На КапперХаб с 2026 года", html)
        self.assertIn("<b>5/9</b>достижений открыто", html)
        for expert_only in (
            "capper-trust-badge", "capper-verified-badge", "expert-leader-badges",
            "expert-mobile-presence", "проходимость", "подписчиков", "прогнозов",
        ):
            self.assertNotIn(expert_only, html)

    def test_capper_keeps_existing_stats_presence_and_badges(self):
        self.context["public_is_capper"] = True
        html = self.render()
        for expected in (
            'class="expert-mobile-card-bg"', "Эксперт КапперХаб", "capper-trust-badge",
            "capper-verified-badge", "expert-leader-badges", "+4", "В сети",
            "<b data-followers-count>123</b>подписчиков", "42</b>прогнозов", "проходимость",
        ):
            self.assertIn(expected, html)
        self.assertNotIn("достижений открыто", html)

    def test_avatar_and_long_name_render_without_unescaped_markup(self):
        self.context["public_user"].avatar = SimpleNamespace(url="/media/profile/avatar.webp")
        self.context["public_name"] = "Длинное имя " * 20 + "<script>bad</script>"
        html = self.render()
        self.assertIn('src="/media/profile/avatar.webp"', html)
        self.assertIn('width="190" height="190"', html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)
