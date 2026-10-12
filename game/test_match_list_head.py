from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from cabinet.models import User
from game.models import League, Match, Prediction, PredictionCoupon, Sport, Team

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class MatchListHeadTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.football = Sport.objects.create(code="football", name="Football", name_ru="Футбол")
        self.hockey = Sport.objects.create(code="ice-hockey", name="Hockey", name_ru="Хоккей")
        self.league = League.objects.create(external_id=1, sport=self.football, name="Premier League", name_ru="АПЛ")
        self.next_id = 931000

    def match(self, sport, *, scope=Match.SyncScope.PREMATCH, hour=15, home="", away=""):
        self.next_id += 1
        starts_at = timezone.make_aware(datetime.combine(self.today, time(hour, 0)), timezone.get_current_timezone())
        teams = {}
        for side, name in (("home_team", home), ("away_team", away)):
            if name:
                self.next_id += 1
                teams[side] = Team.objects.create(external_id=self.next_id, sport=sport, name=name, name_ru=name)
        return Match.objects.create(
            external_id=self.next_id,
            sport=sport,
            sync_scope=scope,
            starts_at=starts_at,
            league=self.league if sport == self.football else None,
            **teams,
        )

    def publish_predictions(self, match, count):
        author = User.objects.create_user(username=f"head-capper-{match.pk}", password="x", role=User.Role.ANALYST)
        for _ in range(count):
            coupon = PredictionCoupon.objects.create(
                author=author,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                audience=PredictionCoupon.Audience.FREE,
                total_stake=Decimal("100"),
                possible_payout=Decimal("200"),
            )
            Prediction.objects.create(
                coupon=coupon, match=match, market="winner", selection="П1", coefficient=Decimal("2"), stake=Decimal("100")
            )

    def url(self, sport="all", scope="all"):
        return f"/games/{sport}/{scope}/{self.today.isoformat()}/"

    def test_head_shows_sport_tiles_with_counts_and_toggles_back_to_all(self):
        self.match(self.football)
        self.match(self.football, hour=16)
        self.match(self.hockey)
        self.match(self.hockey, scope=Match.SyncScope.LIVE)

        response = self.client.get(self.url(sport="football", scope=Match.SyncScope.PREMATCH))

        head = response.context["match_head"]
        tiles = {sport["code"]: sport for sport in head["sports"]}
        self.assertEqual(tiles["football"]["count"], 2)
        self.assertEqual(tiles["ice-hockey"]["count"], 1)
        self.assertEqual(tiles["football"]["tile_key"], "f")
        self.assertEqual(tiles["ice-hockey"]["tile_key"], "h")
        self.assertEqual(tiles["football"]["toggle_url"], self.url(scope=Match.SyncScope.PREMATCH))
        self.assertEqual(tiles["ice-hockey"]["toggle_url"], self.url(sport="ice-hockey", scope=Match.SyncScope.PREMATCH))
        self.assertEqual(head["sports_total"], 3)
        self.assertEqual(head["title_main"], "Предстоящие матчи")
        self.assertContains(response, "data-matches-head")
        self.assertContains(response, "matches-sport-tile is-f is-active")
        self.assertNotContains(response, "matches-mobile-sports-panel")

    def test_search_filters_by_team_and_league_and_is_kept_in_filter_links(self):
        spartak = self.match(self.football, home="Спартак", away="Зенит")
        self.match(self.football, hour=17, home="Динамо", away="Локомотив")
        self.match(self.hockey, home="Авангард", away="СКА")

        response = self.client.get(self.url(), {"q": "  спартак "})

        self.assertEqual([match.id for match in response.context["matches"]], [spartak.id])
        head = response.context["match_head"]
        self.assertEqual(head["search_query"], "спартак")
        self.assertIn("q=%D1%81%D0%BF%D0%B0%D1%80%D1%82%D0%B0%D0%BA", head["sports"][0]["url"])
        self.assertIn("q=", head["scopes"][1]["url"])
        self.assertEqual(response.context["seo_meta"]["robots"], "noindex,follow")

        by_league = self.client.get(self.url(), {"q": "АПЛ"})
        self.assertEqual(len(by_league.context["matches"]), 2)

    def test_popular_sort_puts_matches_with_more_predictions_first(self):
        early = self.match(self.football, hour=12)
        popular = self.match(self.football, hour=18)
        self.publish_predictions(popular, 2)

        by_time = self.client.get(self.url())
        by_popularity = self.client.get(self.url(), {"sort": "popular"})

        self.assertEqual([match.id for match in by_time.context["matches"]], [early.id, popular.id])
        self.assertEqual([match.id for match in by_popularity.context["matches"]], [popular.id, early.id])
        self.assertEqual(by_time.context["match_head"]["sort_label"], "Сначала ближайшие")
        self.assertIn("sort=popular", by_time.context["match_head"]["sort_url"])
        self.assertEqual(by_popularity.context["match_head"]["sort_label"], "Сначала популярные")
        self.assertEqual(by_popularity.context["match_head"]["with_predictions_label"], "1 уже с прогнозами")
        self.assertIn("sort=popular", by_popularity.context["match_head"]["sports"][0]["url"])
        self.assertEqual(by_popularity.context["seo_meta"]["robots"], "index,follow")

    def test_live_head_and_partial_response_render_the_sticky_head(self):
        self.match(self.football, scope=Match.SyncScope.LIVE)

        response = self.client.get("/games/all/live/", {"partial": "matches"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        payload = response.json()
        self.assertIn("matches-head-livepill", payload["hero_html"])
        self.assertIn("<strong>матч в эфире</strong>", payload["hero_html"])
        self.assertNotIn("sport_tabs_html", payload)
        self.assertNotIn("prediction-results-head", payload["content_html"])

    def test_today_counts_live_matches_that_started_before_the_day(self):
        self.match(self.football)
        late_live = self.match(self.hockey, scope=Match.SyncScope.LIVE)
        late_live.starts_at = timezone.now() - timedelta(days=1)
        late_live.save(update_fields=["starts_at"])

        today = self.client.get(self.url())
        tomorrow = self.client.get(f"/games/all/all/{(self.today + timedelta(days=1)).isoformat()}/")

        scope_counts = {tab["scope"]: tab["count"] for tab in today.context["scope_tabs"]}
        self.assertEqual(scope_counts["all"], 2)
        self.assertEqual(scope_counts[Match.SyncScope.LIVE], 1)
        self.assertIn(late_live.id, [match.id for match in today.context["matches"]])
        tiles = {sport["code"]: sport["count"] for sport in today.context["match_head"]["sports"]}
        self.assertEqual(tiles, {"football": 1, "ice-hockey": 1})
        self.assertNotIn(late_live.id, [match.id for match in tomorrow.context["matches"]])
