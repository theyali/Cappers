from unittest.mock import PropertyMock, patch

from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from cabinet.models import AnalystProfile, CapperArticle, User
from front.models import Article, ArticleCategory

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
TEXT = "<p>" + "темп матча и ожидаемые голы " * 80 + "</p>"


@override_settings(STORAGES=TEST_STORAGES)
class CapperArticleTests(TestCase):
    def setUp(self):
        self.capper = User.objects.create_user(username="vadim", password="secret", role=User.Role.ANALYST)
        profile, _ = AnalystProfile.objects.get_or_create(user=self.capper)
        profile.display_name = "Vadim Krylov"
        profile.save()
        self.strategies = ArticleCategory.objects.get_or_create(slug="strategies", defaults={"name": "Стратегии"})[0]
        self.reviews = ArticleCategory.objects.get_or_create(slug="match-reviews", defaults={"name": "Обзоры матчей"})[0]
        vip = patch.object(User, "is_vip", new_callable=PropertyMock, return_value=True)
        vip.start()
        self.addCleanup(vip.stop)

    def _article(self, **fields):
        values = {
            "author": self.capper,
            "title": "Как я выбираю тоталы в АПЛ",
            "slug": "kak-ya-vybirayu-totaly",
            "excerpt": "Разбираю ожидаемые голы по пяти турам.",
            "content": TEXT,
            "category": self.strategies,
            "status": CapperArticle.Status.APPROVED,
            "published_at": timezone.now(),
            **fields,
        }
        return CapperArticle.objects.create(**values)

    # Editor -------------------------------------------------------------------------------

    def test_draft_keeps_category_tags_and_reading_time(self):
        self.client.force_login(self.capper)
        response = self.client.post(reverse("cabinet:capper_article_create"), {
            "title": "Как я выбираю тоталы",
            "excerpt": "Коротко о статье",
            "category": self.strategies.pk,
            "tags": "АПЛ, тоталы, апл, экспресс, xG, лайв, коридоры",
            "content": TEXT,
            "article_action": "draft",
        })

        article = CapperArticle.objects.get()
        self.assertRedirects(response, reverse("cabinet:capper_article_edit", args=[article.pk]), fetch_redirect_response=False)
        self.assertEqual(article.status, CapperArticle.Status.DRAFT)
        self.assertEqual(article.category, self.strategies)
        self.assertEqual(article.tags, "АПЛ, тоталы, экспресс, xG, лайв")
        self.assertEqual(article.reading_time_minutes, 2)

        page = self.client.get(reverse("cabinet:capper_article_edit", args=[article.pk]))
        self.assertContains(page, "Редактирование статьи")
        self.assertContains(page, 'class="article-tag" data-article-tag>экспресс<', html=False)
        self.assertContains(page, "Готовность к отправке")

    def test_empty_submit_lists_errors_at_the_top(self):
        self.client.force_login(self.capper)
        response = self.client.post(reverse("cabinet:capper_article_create"), {"article_action": "submit"})

        self.assertFalse(CapperArticle.objects.exists())
        self.assertContains(response, "Не отправили")
        self.assertContains(response, "Укажите заголовок статьи")
        self.assertContains(response, "Добавьте текст статьи")
        self.assertContains(response, 'href="#id_title"')

    def test_rejected_article_shows_the_moderator_note(self):
        article = self._article(status=CapperArticle.Status.REJECTED, moderation_note="Уберите ссылку на букмекера")
        self.client.force_login(self.capper)
        page = self.client.get(reverse("cabinet:capper_article_edit", args=[article.pk]))
        self.assertContains(page, "Статья отклонена модератором")
        self.assertContains(page, "Уберите ссылку на букмекера")
        self.assertContains(page, "is-rejected")

    def test_old_submit_route_is_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse("cabinet:capper_article_submit", args=[1])

    # Common section -----------------------------------------------------------------------

    def test_articles_section_lists_editorial_and_approved_capper_articles(self):
        Article.objects.create(title="Как читать линию", slug="liniya", description="Гайд", content="<p>x</p>", category=self.reviews)
        self._article()
        self._article(title="Черновик каппера", slug="chernovik", status=CapperArticle.Status.PENDING, published_at=None)

        page = self.client.get(reverse("front:articles"))
        self.assertContains(page, "Как читать линию")
        self.assertContains(page, "Как я выбираю тоталы в АПЛ")
        self.assertNotContains(page, "Черновик каппера")
        self.assertContains(page, f'href="{reverse("front:expert_profile", args=["vadim"])}">Vadim Krylov<')

        cappers = self.client.get(reverse("front:articles"), {"source": "cappers"})
        self.assertNotContains(cappers, "Как читать линию")
        self.assertContains(cappers, "Как я выбираю тоталы в АПЛ")
        editorial = self.client.get(reverse("front:articles"), {"source": "editorial"})
        self.assertNotContains(editorial, "Как я выбираю тоталы в АПЛ")

        by_category = self.client.get(reverse("front:articles"), {"category": "match-reviews"})
        self.assertContains(by_category, "Как читать линию")
        self.assertNotContains(by_category, "Как я выбираю тоталы в АПЛ")
        search = self.client.get(reverse("front:articles"), {"q": "ожидаемые голы"})
        self.assertContains(search, "Как я выбираю тоталы в АПЛ")
        self.assertEqual(self.client.get(reverse("front:articles"), {"sort": "read_time"}).status_code, 200)

    def test_capper_article_page_uses_the_common_article_page(self):
        article = self._article()
        page = self.client.get(article.get_absolute_url())
        self.assertTemplateUsed(page, "front/article_detail.html")
        self.assertContains(page, "Vadim Krylov")
        self.assertContains(page, reverse("front:expert_profile", args=["vadim"]))

        wrong_slug = reverse("front:capper_article_detail", args=["vadim", article.pk, "old-slug"])
        self.assertRedirects(self.client.get(wrong_slug), article.get_absolute_url(), status_code=301)
        pending = self._article(slug="pending", status=CapperArticle.Status.PENDING)
        self.assertEqual(self.client.get(pending.get_absolute_url()).status_code, 404)

    def test_sitemap_lists_approved_capper_articles(self):
        article = self._article()
        self.assertContains(self.client.get("/sitemap.xml"), article.get_absolute_url())


@override_settings(STORAGES=TEST_STORAGES)
class CapperArticleDailyLimitTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from cabinet.models import UserVipSubscription, VipPlan
        self.author = User.objects.create_user(username="article-quota-author", role=User.Role.ANALYST)
        self.plan = VipPlan.objects.create(title="Article quota", duration_days=30, daily_article_limit=2)
        self.subscription = UserVipSubscription.objects.create(user=self.author, plan=self.plan,
            starts_at=timezone.now() - timedelta(days=1), ends_at=timezone.now() + timedelta(days=30), duration_days=31)
        validation = patch("cabinet.services.capper_articles._validate_article_text")
        self.validate = validation.start()
        self.addCleanup(validation.stop)

    def draft(self):
        return CapperArticle.objects.create(author=self.author, title="Разбор матча", content=TEXT)

    def submit(self, article=None):
        from cabinet.services.capper_articles import submit_capper_article_for_moderation
        return submit_capper_article_for_moderation(self.author, article or self.draft())

    def quota(self):
        from cabinet.services.capper_articles import build_article_daily_quota
        return build_article_daily_quota(self.author)

    def test_limit_blocks_third_submission_but_keeps_draft(self):
        from django.core.exceptions import ValidationError
        self.submit()
        self.submit()
        draft = self.draft()
        with self.assertRaisesMessage(ValidationError, "Дневной лимит"):
            self.submit(draft)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")
        self.assertEqual(self.quota(), {"limit": 2, "used": 2, "remaining": 0})

    def test_admin_changes_apply_without_resetting_daily_usage(self):
        from django.core.exceptions import ValidationError
        self.submit()
        for limit in (3, 5):
            self.plan.daily_article_limit = limit
            self.plan.save(update_fields=["daily_article_limit"])
            self.submit()
            self.assertEqual(self.quota()["limit"], limit)
        self.plan.daily_article_limit = 0
        self.plan.save(update_fields=["daily_article_limit"])
        with self.assertRaisesMessage(ValidationError, "отключена"):
            self.submit()
        self.assertEqual(self.quota()["used"], 3)

    def test_rejected_resubmission_uses_another_slot_and_deletion_does_not_refund(self):
        from django.core.exceptions import ValidationError
        article = self.submit()
        article.status = "rejected"
        article.save(update_fields=["status"])
        self.submit(article)
        article.delete()
        self.assertEqual(self.quota()["used"], 2)
        with self.assertRaises(ValidationError):
            self.submit()

    def test_invalid_article_does_not_consume_quota(self):
        from django.core.exceptions import ValidationError
        self.validate.side_effect = ValidationError("Запрещённая ссылка")
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertEqual(self.quota()["used"], 0)

    @override_settings(TIME_ZONE="Asia/Baku")
    def test_limit_resets_at_local_midnight_not_utc_midnight(self):
        from datetime import datetime, timezone as dt_timezone
        from cabinet.services.capper_articles import build_article_daily_quota
        before = datetime(2026, 10, 21, 19, 59, tzinfo=dt_timezone.utc)
        after = datetime(2026, 10, 21, 20, 1, tzinfo=dt_timezone.utc)
        self.subscription.starts_at = before.replace(day=1)
        self.subscription.ends_at = after.replace(month=11)
        self.subscription.save(update_fields=["starts_at", "ends_at"])
        with patch("cabinet.services.capper_articles.timezone.now", return_value=before):
            self.submit()
            self.submit()
        with patch("cabinet.services.capper_articles.timezone.now", return_value=after):
            self.assertEqual(build_article_daily_quota(self.author)["used"], 0)
            self.submit()
            self.assertEqual(build_article_daily_quota(self.author)["used"], 1)

    def test_vip_without_plan_has_safe_default_limit(self):
        self.subscription.plan = None
        self.subscription.save(update_fields=["plan"])
        self.assertEqual(self.quota()["limit"], 2)

    def test_editor_displays_quota_and_limit_error_preserves_text(self):
        self.client.force_login(self.author)
        self.submit()
        self.submit()
        draft = self.draft()
        page = self.client.get(reverse("cabinet:capper_article_edit", args=[draft.pk]))
        self.assertContains(page, "Сегодня отправлено на модерацию: 2 из 2")
        page = self.client.post(reverse("cabinet:capper_article_edit", args=[draft.pk]), {
            "article_action": "submit", "title": "Текст сохранён при лимите", "content": TEXT,
        })
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Дневной лимит статей исчерпан")
        draft.refresh_from_db()
        self.assertEqual(draft.title, "Текст сохранён при лимите")
        self.assertEqual(draft.status, "draft")


@skipUnlessDBFeature("has_select_for_update")
class CapperArticleDailyLimitConcurrencyTests(TransactionTestCase):
    def test_parallel_submissions_share_one_author_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        from datetime import timedelta
        from threading import Barrier
        from django.core.exceptions import ValidationError
        from django.db import connections
        from cabinet.models import CapperArticleDailyUsage, UserVipSubscription, VipPlan
        from cabinet.services.capper_articles import submit_capper_article_for_moderation

        author = User.objects.create_user(username="parallel-article-author", role=User.Role.ANALYST)
        plan = VipPlan.objects.create(title="One article", duration_days=30, daily_article_limit=1)
        UserVipSubscription.objects.create(user=author, plan=plan, starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=30), duration_days=30)
        articles = [CapperArticle.objects.create(author=author, title=f"Матч {i}", content=TEXT) for i in range(2)]
        barrier = Barrier(2)

        def submit(article_id):
            try:
                user = User.objects.get(pk=author.pk)
                article = CapperArticle.objects.get(pk=article_id)
                barrier.wait(timeout=10)
                submit_capper_article_for_moderation(user, article)
                return "submitted"
            except ValidationError:
                return "limited"
            finally:
                connections.close_all()

        with patch("cabinet.services.capper_articles._validate_article_text"), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, [article.pk for article in articles]))
        self.assertCountEqual(results, ["submitted", "limited"])
        self.assertEqual(CapperArticleDailyUsage.objects.get(author=author).submitted_count, 1)
        self.assertEqual(CapperArticle.objects.filter(author=author, status="pending").count(), 1)
