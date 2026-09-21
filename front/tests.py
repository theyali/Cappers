from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from back.models import WebsiteSettings
from cabinet.models import (
    AnalystProfile,
    CapperMonthlyStat,
    User,
    UserLeaguePreference,
    UserSportPreference,
)
from game.models import League, Match, Prediction, PredictionCoupon, Sport

from .expert_ranking import (
    expert_ranking_score,
    rank_experts,
    recommended_experts_for_user,
)


class ExpertRankingScoreTests(SimpleTestCase):
    @staticmethod
    def _profile(*, trust_index, roi, settled_count):
        return SimpleNamespace(
            trust_index=Decimal(str(trust_index)),
            author_roi=Decimal(str(roi)),
            roi_settled_count=settled_count,
            settled_count=settled_count,
        )

    def test_higher_trust_index_beats_extreme_roi_with_lower_trust(self):
        trusted = self._profile(trust_index="8.0", roi="-100", settled_count=100)
        lucky = self._profile(trust_index="7.9", roi="1000", settled_count=3)

        self.assertGreater(
            expert_ranking_score(trusted),
            expert_ranking_score(lucky),
        )

    def test_equal_trust_index_uses_stabilized_roi_as_tie_breaker(self):
        stronger_roi = self._profile(trust_index="8.0", roi="18", settled_count=30)
        weaker_roi = self._profile(trust_index="8.0", roi="6", settled_count=30)

        self.assertGreater(
            expert_ranking_score(stronger_roi),
            expert_ranking_score(weaker_roi),
        )


class CapperTrustRankingIntegrationTests(TestCase):
    august = date(2026, 8, 1)
    september = date(2026, 9, 1)

    @classmethod
    def _create_capper(cls, username: str, trust_index: str):
        user = User.objects.create_user(
            username=username,
            password="test-password",
            role=User.Role.ANALYST,
        )
        profile, _ = AnalystProfile.objects.get_or_create(user=user)
        AnalystProfile.objects.filter(pk=profile.pk).update(
            is_public=True,
            trust_index=Decimal(trust_index),
        )
        return user

    @classmethod
    def _create_stat(
        cls,
        user,
        month,
        *,
        bets,
        wins,
        losses,
        refunds=0,
        stake="1000",
        profit="0",
        flat="0",
        roi="0",
        coefficient="1.90",
        hit_rate="50.0",
    ):
        return CapperMonthlyStat.objects.create(
            analyst=user,
            month=month,
            bets_count=bets,
            wins_count=wins,
            losses_count=losses,
            refunds_count=refunds,
            total_stake=Decimal(stake),
            total_profit=Decimal(profit),
            flat_profit_percent=Decimal(flat),
            roi=Decimal(roi),
            avg_coefficient=Decimal(coefficient),
            hit_rate=Decimal(hit_rate),
        )

    @classmethod
    def setUpTestData(cls):
        # A: strongest all-time trust, no activity in August/September.
        cls.inactive_month_user = cls._create_capper("capper_a_trust", "9.5")
        # B: lower trust, strongest monthly result.
        cls.high_roi_user = cls._create_capper("capper_b_month", "6.0")
        # C: higher trust than B, but weaker monthly result.
        cls.high_trust_user = cls._create_capper("capper_c_month", "7.0")
        cls.third_month_user = cls._create_capper("capper_d_month", "5.0")
        cls.tie_high_trust_user = cls._create_capper("capper_e_tie_high", "8.0")
        cls.tie_low_trust_user = cls._create_capper("capper_f_tie_low", "3.0")

        cls._create_stat(
            cls.inactive_month_user,
            date(2026, 7, 1),
            bets=12,
            wins=8,
            losses=4,
            stake="1200",
            profit="180",
            flat="15.0",
            roi="15.0",
            coefficient="1.85",
            hit_rate="66.7",
        )
        cls._create_stat(
            cls.inactive_month_user,
            cls.august,
            bets=0,
            wins=0,
            losses=0,
            stake="0",
            profit="0",
        )

        cls._create_stat(
            cls.high_trust_user,
            cls.august,
            bets=20,
            wins=11,
            losses=8,
            refunds=1,
            stake="2000",
            profit="60",
            flat="3.0",
            roi="3.0",
            hit_rate="55.0",
        )
        cls._create_stat(
            cls.high_roi_user,
            cls.august,
            bets=3,
            wins=3,
            losses=0,
            stake="300",
            profit="600",
            flat="200.0",
            roi="200.0",
            coefficient="3.00",
            hit_rate="100.0",
        )

        # September data is used by the homepage "experts of the month" block.
        cls._create_stat(
            cls.high_roi_user,
            cls.september,
            bets=12,
            wins=9,
            losses=3,
            stake="1200",
            profit="240",
            flat="20.0",
            roi="20.0",
            hit_rate="75.0",
        )
        cls._create_stat(
            cls.high_trust_user,
            cls.september,
            bets=14,
            wins=9,
            losses=5,
            stake="1400",
            profit="140",
            flat="10.0",
            roi="10.0",
            hit_rate="64.3",
        )
        cls._create_stat(
            cls.third_month_user,
            cls.september,
            bets=10,
            wins=6,
            losses=4,
            stake="1000",
            profit="50",
            flat="5.0",
            roi="5.0",
            hit_rate="60.0",
        )
        cls._create_stat(
            cls.tie_high_trust_user,
            cls.september,
            bets=8,
            wins=3,
            losses=5,
            stake="800",
            profit="-80",
            flat="-10.0",
            roi="-10.0",
            hit_rate="37.5",
        )
        cls._create_stat(
            cls.tie_low_trust_user,
            cls.september,
            bets=8,
            wins=3,
            losses=5,
            stake="800",
            profit="-80",
            flat="-10.0",
            roi="-10.0",
            hit_rate="37.5",
        )

    def test_month_table_uses_month_results_and_excludes_inactive_cappers(self):
        response = self.client.get(
            reverse(
                "front:cappers_table_period",
                kwargs={"group": "all", "period": "2026-08"},
            )
        )

        self.assertEqual(response.status_code, 200)
        usernames = [row["username"] for row in response.context["ranking_rows"]]
        self.assertEqual(
            usernames[:2],
            [self.high_roi_user.username, self.high_trust_user.username],
        )
        self.assertNotIn(self.inactive_month_user.username, usernames)
        self.assertContains(response, ">Индекс</th>", html=False)
        self.assertContains(response, 'title="Общий индекс"')
        self.assertContains(response, "capper-trust-badge")

    def test_equal_month_metrics_use_trust_index_as_tie_breaker(self):
        usernames = [
            entry["profile"].user.username
            for entry in rank_experts(period="2026-09")
        ]
        self.assertLess(
            usernames.index(self.tie_high_trust_user.username),
            usernames.index(self.tie_low_trust_user.username),
        )

    def test_month_table_and_home_month_block_share_same_top_three(self):
        table_response = self.client.get(
            reverse(
                "front:cappers_table_period",
                kwargs={"group": "all", "period": "2026-09"},
            )
        )
        home_response = self.client.get(reverse("front:index"))

        self.assertEqual(table_response.status_code, 200)
        self.assertEqual(home_response.status_code, 200)
        table_top = [
            row["username"]
            for row in table_response.context["ranking_rows"][:3]
        ]
        home_top = [expert["username"] for expert in home_response.context["top_experts"][:3]]
        service_top = [
            entry["profile"].user.username
            for entry in rank_experts(period="2026-09", limit=3)
        ]

        self.assertEqual(table_top, service_top)
        self.assertEqual(home_top, service_top)

    def test_all_time_statistics_and_table_share_canonical_trust_order(self):
        stats_response = self.client.get(
            reverse("front:cappers_stats"),
            {"roi_period": "all"},
        )
        table_response = self.client.get(reverse("front:cappers_table"))

        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(table_response.status_code, 200)

        service_order = [
            entry["profile"].user.username
            for entry in rank_experts(period="all-time")
        ]
        stats_order = [expert["username"] for expert in stats_response.context["experts"]]
        table_order = [row["username"] for row in table_response.context["ranking_rows"]]

        self.assertEqual(stats_order, service_order)
        self.assertEqual(table_order, service_order)
        self.assertEqual(service_order[0], self.inactive_month_user.username)

    def test_changing_month_changes_order_only_through_shared_service(self):
        august_response = self.client.get(
            reverse(
                "front:cappers_table_period",
                kwargs={"group": "all", "period": "2026-08"},
            )
        )
        september_response = self.client.get(
            reverse(
                "front:cappers_table_period",
                kwargs={"group": "all", "period": "2026-09"},
            )
        )

        august_table = [row["username"] for row in august_response.context["ranking_rows"]]
        september_table = [row["username"] for row in september_response.context["ranking_rows"]]
        august_service = [
            entry["profile"].user.username
            for entry in rank_experts(period="2026-08")
        ]
        september_service = [
            entry["profile"].user.username
            for entry in rank_experts(period="2026-09")
        ]

        self.assertEqual(august_table, august_service)
        self.assertEqual(september_table, september_service)
        self.assertNotEqual(august_table, september_table)

    def test_table_explains_all_time_and_month_ranking_modes(self):
        all_time_response = self.client.get(reverse("front:cappers_table"))
        month_response = self.client.get(
            reverse(
                "front:cappers_table_period",
                kwargs={"group": "all", "period": "2026-08"},
            )
        )

        self.assertContains(all_time_response, "Общий рейтинг по индексу доверия.")
        self.assertNotContains(
            all_time_response,
            "Рейтинг за Август 2026 по месячным результатам.",
        )
        self.assertContains(
            month_response,
            "Рейтинг за Август 2026 по месячным результатам.",
        )
        self.assertNotContains(month_response, "Общий рейтинг по индексу доверия.")

    def test_statistics_explains_trust_index_ranking(self):
        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Рейтинг по индексу доверия")
        self.assertContains(
            response,
            "Индекс доверия учитывает ROI, просадку, стабильность, объем истории, средний коэффициент, активность и точность уверенности",
        )


class PersonalizedExpertRecommendationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user(
            username="recommendation-reader",
            password="test-password",
            role=User.Role.READER,
        )
        cls.football = Sport.objects.create(
            code="recommendation-football",
            name="Football",
            name_ru="Футбол",
        )
        cls.tennis = Sport.objects.create(
            code="recommendation-tennis",
            name="Tennis",
            name_ru="Теннис",
        )
        cls.preferred_league = League.objects.create(
            external_id=991001,
            sport=cls.football,
            name="Preferred League",
            name_ru="Любимая лига",
        )
        cls.other_football_league = League.objects.create(
            external_id=991002,
            sport=cls.football,
            name="Other Football League",
            name_ru="Другая футбольная лига",
        )
        cls.tennis_league = League.objects.create(
            external_id=991003,
            sport=cls.tennis,
            name="Tennis League",
            name_ru="Теннисная лига",
        )

        UserSportPreference.objects.create(
            user=cls.reader,
            sport=cls.football,
        )
        UserLeaguePreference.objects.create(
            user=cls.reader,
            league=cls.preferred_league,
        )

        cls.league_capper = cls._create_capper(
            "league-match-capper",
            trust_index="6.0",
        )
        cls.sport_capper = cls._create_capper(
            "sport-match-capper",
            trust_index="9.0",
        )
        cls.unrelated_capper = cls._create_capper(
            "unrelated-capper",
            trust_index="10.0",
        )

        cls._create_published_prediction(
            cls.league_capper,
            cls.preferred_league,
            cls.football,
            external_id=991101,
        )
        cls._create_published_prediction(
            cls.sport_capper,
            cls.other_football_league,
            cls.football,
            external_id=991102,
        )
        cls._create_published_prediction(
            cls.unrelated_capper,
            cls.tennis_league,
            cls.tennis,
            external_id=991103,
        )

    @classmethod
    def _create_capper(cls, username: str, *, trust_index: str):
        user = User.objects.create_user(
            username=username,
            password="test-password",
            role=User.Role.ANALYST,
        )
        profile, _ = AnalystProfile.objects.get_or_create(user=user)
        AnalystProfile.objects.filter(pk=profile.pk).update(
            is_public=True,
            trust_index=Decimal(trust_index),
        )
        return user

    @classmethod
    def _create_published_prediction(
        cls,
        author,
        league,
        sport,
        *,
        external_id: int,
    ):
        match = Match.objects.create(
            external_id=external_id,
            sport=sport,
            league=league,
            sync_scope=Match.SyncScope.PREMATCH,
        )
        coupon = PredictionCoupon.objects.create(
            author=author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100"),
            possible_payout=Decimal("120"),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="home",
            coefficient=Decimal("1.80"),
            stake=Decimal("100"),
        )

    def test_recommendations_prioritize_league_then_sport_and_ignore_unrelated(self):
        with self.assertNumQueries(3):
            profiles = recommended_experts_for_user(self.reader, limit=3)

        self.assertEqual(
            [profile.user.username for profile in profiles],
            [
                self.league_capper.username,
                self.sport_capper.username,
            ],
        )
        self.assertGreater(
            profiles[0].preference_match_score,
            profiles[1].preference_match_score,
        )

    def test_recommendations_return_empty_without_preferences(self):
        user = User.objects.create_user(
            username="reader-without-preferences",
            password="test-password",
            role=User.Role.READER,
        )

        with self.assertNumQueries(2):
            self.assertEqual(recommended_experts_for_user(user), [])


class FooterRenderingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.settings = WebsiteSettings.load()
        self.settings.footer_description = "Тестовое описание футера из админки"
        self.settings.save(update_fields=["footer_description", "updated_at"])
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_home_renders_footer_description_from_website_settings(self):
        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Тестовое описание футера из админки")
        self.assertContains(response, 'class="site-footer site-footer-v2"')

    def test_footer_is_hidden_by_default(self):
        user = User.objects.create_user(
            username="footer-hidden-reader",
            password="test-password",
            role=User.Role.READER,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("front:favorites"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="site-footer site-footer-v2"')
