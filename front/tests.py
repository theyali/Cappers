from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from types import SimpleNamespace

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from back.models import WebsiteSettings
from pages.models import AdvBanner, PageSEO
from cabinet.models import (
    AnalystProfile,
    CapperMonthlyStat,
    User,
    UserLeaguePreference,
    UserSportPreference,
)
from game.models import League, Match, Prediction, PredictionCoupon, Sport

from .models import Article, News, StaticPage

from .expert_ranking import (
    expert_ranking_score,
    rank_experts,
    recommended_experts_for_user,
)


class _PromoBannerNestingParser(HTMLParser):
    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__()
        self.stack = []
        self.banner_inside_filter_matches = None
        self.banner_inside_prediction_sidebar = None

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        classes = set(attr_map.get("class", "").split())
        if "page-promo-banner" in classes:
            ancestors = self.stack
            self.banner_inside_filter_matches = any(
                "filter_matches" in ancestor for ancestor in ancestors
            )
            self.banner_inside_prediction_sidebar = any(
                {
                    "matches-table-filter-sidebar",
                    "prediction-filter-sidebar",
                    "predictions-filter-sidebar",
                    "following-feed-filter-sidebar",
                }.issubset(ancestor)
                for ancestor in ancestors
            )
        if tag not in self.VOID_TAGS:
            self.stack.append(classes)

    def handle_endtag(self, tag):
        if tag not in self.VOID_TAGS and self.stack:
            self.stack.pop()


class PredictionFilterSidebarTemplateTests(SimpleTestCase):
    def test_left_promo_banner_is_sidebar_child_not_filter_matches_child(self):
        promo_banner = SimpleNamespace(
            name="Left promo",
            eyebrow="Promo",
            title="Promo title",
            text="Promo text",
            button_label="Open",
            button_url="/bonuses/",
            image=SimpleNamespace(url="/media/promo_banners/test.png"),
            mobile_image=None,
            variant="center_wide",
            title_color="#050505",
            text_color="rgba(0, 0, 0, .76)",
            button_color="#151719",
            button_text_color="#fff200",
        )
        html = render_to_string(
            "front/includes/_prediction_filter_sidebar.html",
            {
                "filter_id_prefix": "following-feed-filter",
                "filter_variant": "following-feed-filter-sidebar",
                "filter_label": "Фильтры моей ленты",
                "filter_total": 0,
                "status_tabs": [],
                "active_sort": "new",
                "active_status": "all",
                "filter_action_url": "/feed/",
                "left_promo_banners": [promo_banner],
            },
        )

        parser = _PromoBannerNestingParser()
        parser.feed(html)

        self.assertTrue(parser.banner_inside_prediction_sidebar)
        self.assertFalse(parser.banner_inside_filter_matches)


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

    def test_home_top_experts_limit_comes_from_page_seo(self):
        PageSEO.objects.update_or_create(
            route_name="front:index",
            exact_path="",
            defaults={
                "name": "Главная",
                "home_top_experts_limit": 5,
            },
        )

        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["top_experts"]), 5)

    def test_all_time_table_uses_canonical_trust_order(self):
        table_response = self.client.get(reverse("front:cappers_table"))

        self.assertEqual(table_response.status_code, 200)

        service_order = [
            entry["profile"].user.username
            for entry in rank_experts(period="all-time")
        ]
        table_order = [row["username"] for row in table_response.context["ranking_rows"]]

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

    def test_table_explains_trust_index_ranking(self):
        response = self.client.get(reverse("front:cappers_table"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Общий рейтинг по индексу доверия.")


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

    def test_public_content_pages_render_footer(self):
        Article.objects.create(
            title="Test article layout 2",
            slug="test-article-layout-2",
            description="Описание статьи",
            content="<p>Статья</p>",
        )
        News.objects.create(
            title="Тестовая новость",
            slug="testovaya-novost",
            description="Описание новости",
            content="<p>Новость</p>",
        )
        for slug, title in (
            ("privacy-policy", "Политика конфиденциальности"),
            ("user-agreement", "Пользовательское соглашение"),
            ("cookie-policy", "Cookie policy"),
        ):
            StaticPage.objects.update_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "content": f"<p>{title}</p>",
                    "is_published": True,
                },
            )
        cache.clear()

        urls = [
            reverse("front:wiki"),
            reverse("front:sports_news"),
            reverse("front:how_it_works"),
            reverse("front:bonuses"),
            reverse("front:bookmakers"),
            reverse("front:article_detail", kwargs={"slug": "test-article-layout-2"}),
            reverse("front:news_detail", kwargs={"slug": "testovaya-novost"}),
            reverse("front:static_page", kwargs={"slug": "privacy-policy"}),
            reverse("front:static_page", kwargs={"slug": "user-agreement"}),
            reverse("front:static_page", kwargs={"slug": "cookie-policy"}),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="site-footer site-footer-v2"')


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class DocumentPagesTests(TestCase):
    def setUp(self):
        cache.clear()
        StaticPage.objects.update_or_create(
            slug="privacy-policy",
            defaults={
                "title": "Политика конфиденциальности",
                "content": "<p>Текст политики</p>",
                "is_published": True,
            },
        )

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_document_pages_use_three_columns_and_show_footer(self):
        urls = [
            reverse("front:about"),
            reverse("front:rules"),
            reverse("front:static_page", kwargs={"slug": "privacy-policy"}),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "predictions-page document-page")
                self.assertContains(response, 'aria-label="Промо слева"')
                self.assertContains(response, 'class="bookmakers-sidebar"')
                self.assertContains(response, '<footer class="site-footer')

    def test_about_page_is_the_home_about_block_with_its_own_heading(self):
        response = self.client.get(reverse("front:about"))

        self.assertContains(response, 'class="home-about"')
        self.assertContains(response, '<h1 id="homeAboutTitle">')
        self.assertContains(response, '<span aria-current="page">О нас</span>', html=True)

    def test_footer_links_to_about_and_rules(self):
        response = self.client.get(reverse("front:rules"))

        self.assertContains(response, '<a href="/about/">О нас</a>', html=True)
        self.assertContains(response, '<a href="/rules/">Правила</a>', html=True)

    def test_rules_contents_link_to_every_section(self):
        response = self.client.get(reverse("front:rules"))

        for number in range(1, 11):
            self.assertContains(response, f'href="#rules-{number}"')
            self.assertContains(response, f'id="rules-{number}"')

    def test_static_page_breadcrumbs_end_with_the_page_title(self):
        response = self.client.get(reverse("front:static_page", kwargs={"slug": "privacy-policy"}))

        self.assertContains(
            response,
            '<span aria-current="page">Политика конфиденциальности</span>',
            html=True,
        )
        self.assertNotContains(response, "Страница</span>")

    def test_ads_go_to_the_right_sidebar_even_if_the_page_says_content(self):
        banner = AdvBanner.objects.create(
            name="Document ad",
            size=AdvBanner.Size.FULL_240,
            image="ads/document-test.png",
            url="https://example.com/document-ad",
        )
        page = PageSEO.objects.create(
            name="Правила",
            route_name="front:rules",
            adv_placement=PageSEO.AdvPlacement.CONTENT,
        )
        page.adv_banners.add(banner)
        cache.clear()

        response = self.client.get(reverse("front:rules"))

        self.assertContains(response, "yjs-additional-b--sidebar")
        self.assertNotContains(response, "yjs-additional-b--content")
        self.assertContains(response, "https://example.com/document-ad")


class SeoInfrastructureTests(TestCase):
    def test_robots_txt_uses_admin_content_and_sitemap_placeholder(self):
        settings = WebsiteSettings.load()
        settings.robots_txt = "User-agent: *\nDisallow: /cabinet/\nSitemap: {sitemap_url}"
        settings.save(update_fields=["robots_txt", "updated_at"])

        response = self.client.get(reverse("robots_txt"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        content = response.content.decode()
        self.assertIn("Disallow: /cabinet/", content)
        self.assertIn("Sitemap: http://testserver/sitemap.xml", content)

    def test_sitemap_contains_published_articles_news_and_matches(self):
        article = Article.objects.create(
            title="Sitemap article",
            slug="sitemap-article",
            description="Описание статьи",
            content="<p>Статья</p>",
        )
        hidden_article = Article.objects.create(
            title="Hidden sitemap article",
            slug="hidden-sitemap-article",
            description="Описание скрытой статьи",
            content="<p>Скрытая статья</p>",
            is_published=False,
        )
        news = News.objects.create(
            title="Sitemap news",
            slug="sitemap-news",
            description="Описание новости",
            content="<p>Новость</p>",
        )
        match = Match.objects.create(
            external_id=991001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now(),
        )

        response = self.client.get(reverse("sitemap"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(f"http://testserver{reverse('front:articles')}", content)
        self.assertIn(f"http://testserver{reverse('front:sports_news')}", content)
        self.assertIn(f"http://testserver{reverse('game:match_list')}", content)
        self.assertIn(f"http://testserver{article.get_absolute_url()}", content)
        self.assertIn(f"http://testserver{news.get_absolute_url()}", content)
        self.assertIn(f"http://testserver{match.get_absolute_url()}", content)
        self.assertNotIn(hidden_article.get_absolute_url(), content)


class ArticleMainTests(TestCase):
    def test_only_one_article_can_be_main(self):
        first = Article.objects.create(
            title="Первая главная статья",
            slug="first-main-article",
            description="Описание первой статьи",
            content="<p>Первая статья</p>",
            is_main=True,
        )
        second = Article.objects.create(
            title="Вторая главная статья",
            slug="second-main-article",
            description="Описание второй статьи",
            content="<p>Вторая статья</p>",
            is_main=True,
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertFalse(first.is_main)
        self.assertTrue(second.is_main)
        self.assertEqual(Article.objects.filter(is_main=True).count(), 1)

    def test_main_article_is_first_and_uses_featured_card(self):
        main_article = Article.objects.create(
            title="Главная статья",
            slug="main-article",
            description="Описание главной статьи",
            content="<p>Главная статья</p>",
            is_main=True,
        )
        Article.objects.create(
            title="Новая обычная статья",
            slug="new-regular-article",
            description="Описание обычной статьи",
            content="<p>Обычная статья</p>",
        )

        response = self.client.get(reverse("front:articles"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].object_list[0].pk, main_article.pk)
        self.assertContains(response, 'class="article-list-card is-main"')


class SportsNewsTests(TestCase):
    def test_sports_news_uses_news_model(self):
        Article.objects.create(
            title="Статья не должна попасть в новости",
            slug="article-not-news",
            description="Описание статьи",
            content="<p>Статья</p>",
        )
        news = News.objects.create(
            title="Отдельная спортивная новость",
            slug="separate-sports-news",
            description="Описание новости",
            content="<p>Новость</p>",
        )

        response = self.client.get(reverse("front:sports_news"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].object_list[0].pk, news.pk)
        self.assertContains(response, "Отдельная спортивная новость")
        self.assertNotContains(response, "Статья не должна попасть в новости")

    def test_only_one_news_can_be_main(self):
        first = News.objects.create(
            title="Первая главная новость",
            slug="first-main-news",
            description="Описание первой новости",
            content="<p>Первая новость</p>",
            is_main=True,
        )
        second = News.objects.create(
            title="Вторая главная новость",
            slug="second-main-news",
            description="Описание второй новости",
            content="<p>Вторая новость</p>",
            is_main=True,
        )

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertFalse(first.is_main)
        self.assertTrue(second.is_main)
        self.assertEqual(News.objects.filter(is_main=True).count(), 1)
