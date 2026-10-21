from unittest.mock import PropertyMock, patch

from django.test import TestCase, override_settings
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
