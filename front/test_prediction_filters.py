from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import League, Match, Prediction, PredictionCoupon, Sport

from .models import PredictionFavorite, PredictionLike


class PredictionFiltersTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(
            external_id=901,
            code="football-filter-test",
            name="Football",
            name_ru="Футбол",
        )
        self.league = League.objects.create(
            external_id=902,
            sport=self.sport,
            name="Filter League",
            name_ru="Тестовая лига",
        )
        self.analyst = User.objects.create_user(
            username="filter-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="filter-reader",
            password="test-password",
            role=User.Role.READER,
        )

    def _prediction(
        self,
        *,
        external_id: int,
        author=None,
        state=Prediction.StateStatus.WIN,
        coefficient="2.00",
        scope=Match.SyncScope.LIVE,
        coupon_state=PredictionCoupon.StateStatus.WIN,
        payout="200.00",
    ):
        author = author or self.analyst
        match = Match.objects.create(
            external_id=external_id,
            sport=self.sport,
            league=self.league,
            sync_scope=scope,
            starts_at=timezone.now(),
            score="1-1",
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Хозяева"}},
                    "away": {"name": {"ru": "Гости"}},
                }
            },
        )
        coupon = PredictionCoupon.objects.create(
            author=author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=coupon_state,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal(payout),
            confidence=76,
            published_at=timezone.now(),
            settled_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="total",
            selection="ТБ 2.5",
            coefficient=Decimal(coefficient),
            stake=Decimal("100.00"),
            state_status=state,
        )
        return coupon

    def test_filters_can_be_combined(self):
        prediction = self._prediction(external_id=910, coefficient="2.15")
        self._prediction(
            external_id=911,
            coefficient="4.50",
            scope=Match.SyncScope.PREMATCH,
            state="",
            coupon_state=PredictionCoupon.StateStatus.PENDING,
            payout="450.00",
        )

        response = self.client.get(
            reverse("front:predictions"),
            {
                "sport": self.sport.id,
                "league": self.league.id,
                "capper": self.analyst.username,
                "coef_min": "2.00",
                "coef_max": "2.50",
                "status": "win",
                "live": "1",
                "today": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filtered_predictions"], 1)
        self.assertEqual(response.context["page_obj"].object_list[0].id, prediction.id)

    def test_popular_sort_uses_likes_and_favorites(self):
        first = self._prediction(external_id=920)
        popular = self._prediction(external_id=921)
        PredictionLike.objects.create(prediction=popular, user=self.reader)
        PredictionFavorite.objects.create(prediction=popular, user=self.reader)

        response = self.client.get(reverse("front:predictions"), {"sort": "popular"})

        self.assertEqual(response.status_code, 200)
        ids = [item.id for item in response.context["page_obj"].object_list]
        self.assertEqual(ids[0], popular.id)
        self.assertIn(first.id, ids)

    def test_roi_sort_uses_settled_coupon_profit(self):
        losing_analyst = User.objects.create_user(
            username="losing-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        best = self._prediction(
            external_id=930,
            author=self.analyst,
            coupon_state=PredictionCoupon.StateStatus.WIN,
            payout="250.00",
        )
        self._prediction(
            external_id=931,
            author=losing_analyst,
            state=Prediction.StateStatus.LOSE,
            coupon_state=PredictionCoupon.StateStatus.LOSE,
            payout="0.00",
        )

        response = self.client.get(reverse("front:predictions"), {"sort": "roi"})

        self.assertEqual(response.status_code, 200)
        items = response.context["page_obj"].object_list
        self.assertEqual(items[0].id, best.id)
        self.assertGreater(items[0].author_roi, 0)
        self.assertContains(response, "ROI +150.0%")
        self.assertContains(response, "prediction-author-roi is-positive")

    def test_filters_render_in_right_sidebar_with_ajax_assets(self):
        self._prediction(external_id=940)

        response = self.client.get(reverse("front:predictions"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('class="predictions-layout" data-predictions-layout', html)
        self.assertIn('class="prediction-filter-sidebar" data-prediction-filter-sidebar', html)
        self.assertIn('data-prediction-filter-toggle', html)
        self.assertIn('data-prediction-filters', html)
        self.assertIn("front/css/predictions-sidebar.css", html)
        self.assertIn("https://code.jquery.com/jquery-3.7.1.min.js", html)
        self.assertIn("front/js/predictions-filters.js", html)
        self.assertLess(html.index('data-predictions-content'), html.index('data-prediction-filter-sidebar'))
        self.assertNotIn("Настроить ленту", html)
        self.assertNotIn("prediction-filter-hint", html)

    def test_sort_control_is_in_results_head_not_sidebar(self):
        self._prediction(external_id=941)

        response = self.client.get(
            reverse("front:predictions"),
            {"sport": self.sport.id, "sort": "popular"},
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        results_start = html.index('class="prediction-results-head"')
        sidebar_start = html.index('class="prediction-filter-sidebar"')
        sidebar_end = html.index("</aside>", sidebar_start)
        sidebar_html = html[sidebar_start:sidebar_end]
        results_html = html[results_start:sidebar_start]

        self.assertIn('data-prediction-sort', results_html)
        self.assertIn('<option value="popular" selected>', results_html)
        self.assertNotIn('data-prediction-sort', sidebar_html)
        self.assertNotIn('<select name="sort"', sidebar_html)
        self.assertIn('<input type="hidden" name="sort" value="popular">', sidebar_html)

    def test_pagination_keeps_active_filter_query(self):
        for index in range(25):
            self._prediction(external_id=1000 + index)

        response = self.client.get(
            reverse("front:predictions"),
            {
                "sport": self.sport.id,
                "status": "win",
                "sort": "roi",
                "page": "2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(response.context["filtered_predictions"], 25)
        self.assertEqual(
            response.context["pagination_query"],
            f"sport={self.sport.id}&status=win&sort=roi",
        )
        self.assertContains(response, "page=1")
        self.assertContains(response, f"sport={self.sport.id}")
        self.assertContains(response, "status=win")
        self.assertContains(response, "sort=roi")
