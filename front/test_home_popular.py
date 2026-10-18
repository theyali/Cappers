from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from front.expert_ranking import rebuild_expert_ranking_snapshot
from front.popular_matches import build_home_popular_links, build_popular_matches
from game.models import League, Match, Sport, Team


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
)
class HomePopularLinksTests(TestCase):
    def setUp(self):
        cache.clear()
        self.sport = Sport.objects.create(
            external_id=2, code="football", name="Football"
        )
        self.now = timezone.now()

    def match(self, pk, rating, *, hours=1, phase="prematch"):
        league = League.objects.create(
            external_id=pk, sport=self.sport, name=f"League {pk}", raw_data=rating
        )
        home = Team.objects.create(
            external_id=pk * 2, sport=self.sport, name=f"Home {pk}"
        )
        away = Team.objects.create(
            external_id=pk * 2 + 1, sport=self.sport, name=f"Away {pk}"
        )
        return Match.objects.create(
            external_id=pk,
            league=league,
            sport=self.sport,
            home_team=home,
            away_team=away,
            sync_scope=phase,
            starts_at=self.now + timedelta(hours=hours),
        )

    @patch("front.popular_matches.POPULAR_MATCHES_SCAN_LIMIT", 1)
    def test_higher_league_rating_wins_before_candidate_limit(self):
        self.match(101, {"rating": 10})
        important = self.match(102, {"rating": 20}, hours=6)
        links = build_home_popular_links()
        self.assertEqual(links[0]["label"], important.league.name)
        self.assertEqual(
            links[1],
            {"label": "Home 102 — Away 102", "url": important.get_absolute_url()},
        )

    def test_numeric_aliases_and_invalid_provider_values(self):
        self.match(101, {"rating": "not a rating"})
        self.match(102, {"rating": 10})
        important = self.match(103, {"rating": 0, "priority": "20,5"})
        match = build_popular_matches(limit=1)[0]
        self.assertEqual(match.id, important.pk)
        self.assertEqual(match.league_rating, 20.5)

    @patch("front.popular_matches.POPULAR_MATCHES_SCAN_LIMIT", 1)
    def test_admin_top_league_weight_is_descending_and_overrides_provider_value(self):
        for pk, priority, provider_rating in ((101, 10, 999), (102, 20, 1)):
            match = self.match(pk, {"rating": provider_rating}, hours=pk - 100)
            match.league.is_top = True
            match.league.top_order = priority
            match.league.save(update_fields=["is_top", "top_order"])
        selected = build_popular_matches(limit=1)[0]
        self.assertEqual(selected.id, match.pk)
        self.assertEqual(selected.league_rating, 20)

    def test_unmarked_league_does_not_use_the_default_admin_top_order(self):
        self.match(101, {})
        important = self.match(102, {"rating": 10})
        selected = build_popular_matches(limit=1)[0]
        self.assertEqual(selected.id, important.pk)
        self.assertEqual(selected.league_rating, 10)

    def test_expired_and_non_prematch_games_are_not_suggestions(self):
        self.match(101, {"rating": 100}, hours=-1)
        self.match(102, {"rating": 100}, phase="finished")
        self.match(103, {"rating": 100}, phase="live")
        self.assertEqual(
            build_home_popular_links(),
            [
                {
                    "label": "Экспрессы на сегодня",
                    "url": reverse("front:prediction_expresses"),
                }
            ],
        )

    def test_home_uses_the_all_time_expert_not_the_month_block_winner(self):
        all_time = User.objects.create_user(
            username="all-time-winner", role=User.Role.ANALYST
        )
        profile = all_time.analyst_profile
        profile.display_name = "Лучший за всё время"
        profile.trust_index = Decimal("9.0")
        profile.save()
        monthly = User.objects.create_user(
            username="month-winner", role=User.Role.ANALYST
        )
        monthly.analyst_profile.trust_index = Decimal("5.0")
        monthly.analyst_profile.save()
        rebuild_expert_ranking_snapshot(period="all-time", roi_period_days=None)
        with patch(
            "front.home_views.current_month_top_expert_ids", return_value=[monthly.pk]
        ):
            response = self.client.get(reverse("front:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["top_experts"][0]["username"], monthly.username
        )
        self.assertIn(
            {
                "label": profile.display_name,
                "url": reverse(
                    "front:expert_profile",
                    kwargs={
                        "username": all_time.username,
                    },
                ),
            },
            response.context["popular_search_links"],
        )
        popular = (
            response.content.decode()
            .split('aria-label="Популярные запросы"', 1)[1]
            .split("</div>", 1)[0]
        )
        self.assertIn(profile.display_name, popular)
        self.assertNotIn("Kirill Pavlenko", popular)
        self.assertNotIn("Лига чемпионов", popular)
