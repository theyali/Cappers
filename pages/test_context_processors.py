from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from .context_processors import page_seo
from .models import AdvBanner, PageSEO


class PageSeoRouteInheritanceTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_filtered_games_urls_inherit_base_games_page_banners(self):
        banner = AdvBanner.objects.create(
            name="Games banner",
            size=AdvBanner.Size.FULL_240,
            image="ads/games-test.png",
            url="https://example.com/",
        )
        page = PageSEO.objects.create(
            name="Матчи",
            route_name="game:match_list",
            exact_path="/games/",
        )
        page.adv_banners.add(banner)

        request = self.factory.get("/games/football/all/2026-08-29/")
        request.user = AnonymousUser()
        request.resolver_match = SimpleNamespace(
            view_name="game:match_list_filtered",
            kwargs={
                "sport": "football",
                "scope": "all",
                "selected_date": "2026-08-29",
            },
        )

        context = page_seo(request)

        self.assertEqual(context["seo_meta"]["page"].pk, page.pk)
        self.assertEqual([item.pk for item in context["adv_banners"]], [banner.pk])

    def test_specific_filtered_seo_keeps_priority_but_inherits_base_banner(self):
        banner = AdvBanner.objects.create(
            name="Games fallback banner",
            size=AdvBanner.Size.FULL_240,
            image="ads/games-fallback.png",
            url="https://example.com/",
        )
        base_page = PageSEO.objects.create(
            name="Матчи",
            route_name="game:match_list",
            exact_path="/games/",
        )
        base_page.adv_banners.add(banner)
        filtered_page = PageSEO.objects.create(
            name="Футбол за дату",
            route_name="game:match_list_filtered",
            exact_path="/games/football/all/2026-08-29/",
            meta_title="Футбол за дату",
        )

        request = self.factory.get("/games/football/all/2026-08-29/")
        request.user = AnonymousUser()
        request.resolver_match = SimpleNamespace(
            view_name="game:match_list_filtered",
            kwargs={},
        )

        context = page_seo(request)

        self.assertEqual(context["seo_meta"]["page"].pk, filtered_page.pk)
        self.assertEqual(context["seo_meta"]["title"], "Футбол за дату")
        self.assertNotEqual(context["seo_meta"]["page"].pk, base_page.pk)
        self.assertEqual([item.pk for item in context["adv_banners"]], [banner.pk])
