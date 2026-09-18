from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from cabinet.models import User

from .context_processors import page_seo
from .models import AdvBanner, PagePromoBanner, PageSEO, PromoBanner
from .promo_banners import promo_banner_matches_user


class PageSeoRouteInheritanceTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

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


    def test_promo_banner_group_preserves_configured_variant(self):
        banner = PromoBanner.objects.create(
            name="Sidebar promo",
            image="promo_banners/sidebar-test.png",
            button_url="/bonuses/",
            variant=PromoBanner.Variant.SIDEBAR_TALL,
        )
        page = PageSEO.objects.create(
            name="Профиль",
            route_name="cabinet:profile",
            exact_path="/cabinet/profile/",
        )
        PagePromoBanner.objects.create(
            page=page,
            banner=banner,
            placement=PagePromoBanner.Placement.RIGHT,
            sort_order=10,
        )

        request = self.factory.get("/cabinet/profile/")
        request.user = AnonymousUser()
        request.resolver_match = SimpleNamespace(
            view_name="cabinet:profile",
            kwargs={},
        )

        context = page_seo(request)
        resolved_banner = context["right_promo_banners"][0]

        self.assertEqual(
            resolved_banner.variant,
            PromoBanner.Variant.SIDEBAR_TALL,
        )


class PromoBannerAudienceTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def _banner(self, audience):
        return PromoBanner(
            audience=audience,
            button_url="/",
            image="promo_banners/test.png",
        )

    def test_promo_banner_matches_user_for_all_audiences(self):
        anonymous = AnonymousUser()
        reader = User(username="reader", role=User.Role.READER)
        capper = User(username="capper", role=User.Role.ANALYST)
        vip_capper = User(username="vip-capper", role=User.Role.ANALYST)
        capper.__dict__["_promo_banner_is_vip"] = False
        vip_capper.__dict__["_promo_banner_is_vip"] = True

        self.assertTrue(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.ALL),
                anonymous,
            )
        )
        self.assertTrue(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.ANONYMOUS),
                anonymous,
            )
        )
        self.assertFalse(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.AUTHENTICATED),
                anonymous,
            )
        )
        self.assertTrue(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.AUTHENTICATED),
                reader,
            )
        )
        self.assertTrue(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.READER),
                reader,
            )
        )
        self.assertFalse(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.CAPPER),
                reader,
            )
        )
        self.assertTrue(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.CAPPER),
                capper,
            )
        )
        self.assertTrue(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.VIP_CAPPER),
                vip_capper,
            )
        )
        self.assertFalse(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.VIP_CAPPER),
                capper,
            )
        )
        self.assertTrue(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.NON_VIP_CAPPER),
                capper,
            )
        )
        self.assertFalse(
            promo_banner_matches_user(
                self._banner(PromoBanner.Audience.NON_VIP_CAPPER),
                vip_capper,
            )
        )

    def test_page_context_filters_audience_after_shared_cache(self):
        page = PageSEO.objects.create(
            name="Матчи audience",
            route_name="game:match_list",
            exact_path="/games/",
        )
        anonymous_banner = PromoBanner.objects.create(
            name="Guest promo",
            image="promo_banners/guest.png",
            button_url="/",
            audience=PromoBanner.Audience.ANONYMOUS,
        )
        reader_banner = PromoBanner.objects.create(
            name="Reader promo",
            image="promo_banners/reader.png",
            button_url="/",
            audience=PromoBanner.Audience.READER,
        )
        for order, banner in enumerate(
            (anonymous_banner, reader_banner),
            start=1,
        ):
            PagePromoBanner.objects.create(
                page=page,
                banner=banner,
                placement=PagePromoBanner.Placement.CENTER,
                sort_order=order,
            )

        anonymous_request = self.factory.get("/games/")
        anonymous_request.user = AnonymousUser()
        anonymous_request.resolver_match = SimpleNamespace(
            view_name="game:match_list",
            kwargs={},
        )
        anonymous_context = page_seo(anonymous_request)

        reader = User.objects.create_user(
            username="promo-reader",
            password="test-password",
            role=User.Role.READER,
        )
        reader_request = self.factory.get("/games/")
        reader_request.user = reader
        reader_request.resolver_match = SimpleNamespace(
            view_name="game:match_list",
            kwargs={},
        )
        reader_context = page_seo(reader_request)

        self.assertEqual(
            [banner.pk for banner in anonymous_context["center_promo_banners"]],
            [anonymous_banner.pk],
        )
        self.assertEqual(
            [banner.pk for banner in reader_context["center_promo_banners"]],
            [reader_banner.pk],
        )
