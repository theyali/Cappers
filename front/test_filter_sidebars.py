from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.models import AnalystFollow, User
from pages.models import AdvBanner, PageSEO


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class AjaxFilterSidebarTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(
            username="sidebar-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.alpha = User.objects.create_user(
            username="alpha-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.beta = User.objects.create_user(
            username="beta-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )

        self.alpha.analyst_profile.display_name = "Alpha Expert"
        self.alpha.analyst_profile.is_verified = True
        self.alpha.analyst_profile.save(
            update_fields=["display_name", "is_verified", "updated_at"]
        )

        self.beta.analyst_profile.display_name = "Beta Expert"
        self.beta.analyst_profile.save(update_fields=["display_name", "updated_at"])

        AnalystFollow.objects.create(follower=self.reader, analyst=self.alpha)

    def test_feed_uses_prediction_style_ajax_sidebar(self):
        self.client.force_login(self.reader)

        response = self.client.get(
            reverse("front:following_feed"),
            {
                "capper": self.alpha.username,
                "live": "1",
                "sort": "popular",
            },
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")

        self.assertIn('class="predictions-layout following-feed-layout"', html)
        self.assertIn("matches-table-filter-sidebar prediction-filter-sidebar predictions-filter-sidebar following-feed-filter-sidebar", html)
        self.assertIn("matches-table-sport-list following-feed-filter-quick", html)
        self.assertIn("data-prediction-filters", html)
        self.assertIn("data-prediction-sort", html)
        self.assertIn("predictions-filters.js", html)
        self.assertIn("code.jquery.com/jquery-3.7.1.min.js", html)
        self.assertLess(html.index("data-prediction-filter-sidebar"), html.index("data-predictions-content"))
        self.assertLess(html.index("data-predictions-content"), html.index('class="bookmakers-sidebar'))
        self.assertNotIn('class="following-feed-controls"', html)
        self.assertNotIn('class="following-cappers-panel"', html)
        self.assertNotIn("predictions-pagination", html)
        self.assertEqual(response.context["active_filter_count"], 2)
        self.assertEqual(response.context["adv_placement"], "sidebar")

    def test_feed_banners_render_in_right_sidebar(self):
        banner = AdvBanner.objects.create(
            name="Feed Sidebar Banner",
            image="ads/feed-sidebar.jpg",
            url="https://example.test/feed",
        )
        page = PageSEO.objects.create(
            name="Feed SEO",
            route_name="front:following_feed",
            exact_path="/feed/",
            adv_placement=PageSEO.AdvPlacement.CONTENT,
        )
        page.adv_banners.add(banner)
        self.client.force_login(self.reader)

        response = self.client.get(reverse("front:following_feed"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertEqual(response.context["adv_placement"], "sidebar")
        self.assertIn('class="predictions-ad-sidebar coupon-sidebar coupon-sidebar-ads"', html)
        self.assertIn("adv-banners--sidebar", html)
        self.assertIn("Feed Sidebar Banner", html)
        self.assertNotIn("adv-banners--content", html)

    def test_cappers_catalog_has_no_filter_sidebar(self):
        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")

        self.assertIn('class="cappers-page cappers-layout"', html)
        self.assertIn('class="cappers-pro-grid"', html)
        self.assertIn('class="bookmakers-sidebar"', html)
        self.assertNotIn("cappers-filter-sidebar", html)
        self.assertNotIn("data-prediction-filters", html)
        self.assertNotIn("data-prediction-sort", html)
        self.assertNotIn("predictions-filters.js", html)
        self.assertNotIn("code.jquery.com/jquery-3.7.1.min.js", html)
