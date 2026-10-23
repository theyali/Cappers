from unittest.mock import PropertyMock, patch

from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from cabinet.comments.models import Comment, CommentReaction
from cabinet.forms import CapperArticleForm
from cabinet.models import AnalystProfile, CapperArticle, User
from front.models import Article, News, PublicationReaction, PublicationSlug
from front.publications import PublicationHTML, publication_body


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class PublicationDetailTests(TestCase):
    def article(self, model=Article, **kwargs):
        return model.objects.create(
            title="Как читать линию",
            description="Описание материала",
            content="<p>Вступление.</p><h2>Сигналы</h2><p>Разбор.</p>",
            **kwargs,
        )

    def test_editorial_article_has_no_author_or_empty_optional_blocks(self):
        article = self.article()
        page = self.client.get(article.get_absolute_url())
        self.assertEqual(page.status_code, 200)
        self.assertIn("no-store", page.headers["Cache-Control"])
        self.assertContains(page, 'class="publication-detail"')
        self.assertNotContains(page, 'class="publication-byline"')
        self.assertNotContains(page, 'class="publication-author-card"')
        self.assertNotContains(page, 'class="publication-toc"')
        self.assertNotContains(page, 'class="publication-inline-link"')
        self.assertNotContains(page, 'class="publication-quote"')
        self.assertContains(
            page,
            'class="matches-table-filter-sidebar prediction-filter-sidebar predictions-filter-sidebar"',
        )
        self.assertContains(page, 'class="bookmakers-sidebar"')

    def test_news_use_same_design_without_author(self):
        news = self.article(News)
        page = self.client.get(news.get_absolute_url())
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="publication-detail"')
        self.assertNotContains(page, 'class="publication-byline"')
        self.assertIsNone(page.context["publication_author"])
        self.assertTrue(page.context["publication_is_news"])

    def test_optional_blocks_render_with_real_heading_anchors(self):
        article = self.article(
            table_of_contents="Сигналы\nНесуществующий раздел",
            pull_quote="Цитата автора",
            related_link_url="/articles/other/",
            related_link_title="Связанный материал",
            summary="Краткий вывод",
            quote_after_paragraph=1,
        )
        page = self.client.get(article.get_absolute_url())
        self.assertContains(page, 'href="#section-1"')
        self.assertContains(page, '<h2 id="section-1">Сигналы</h2>', html=True)
        self.assertNotContains(page, "Несуществующий раздел")
        self.assertContains(page, 'class="publication-inline-link"')
        self.assertContains(page, "Краткий вывод")
        html = page.content.decode()
        self.assertLess(html.index("Цитата автора"), html.index('<h2 id="section-1">'))

    def test_incomplete_related_link_is_hidden(self):
        article = self.article(related_link_url="/articles/other/")
        self.assertNotContains(
            self.client.get(article.get_absolute_url()),
            'class="publication-inline-link"',
        )

    def test_disabled_comments_hide_form_and_reject_post(self):
        article = self.article(comments_enabled=False)
        user = User.objects.create_user(username="reader")
        self.client.force_login(user)
        page = self.client.get(article.get_absolute_url())
        self.assertNotContains(page, 'id="publication-comments"')
        self.client.post(
            article.get_absolute_url(),
            {"action": "comment", "text": "Новый комментарий"},
        )
        self.assertFalse(article.publication_comments.exists())

    def test_views_are_counted_once_per_session(self):
        article = self.article()
        for _ in range(2):
            self.client.get(article.get_absolute_url())
        article.refresh_from_db()
        self.assertEqual(article.views_count, 1)

    def test_real_author_is_rendered_and_author_filter_works(self):
        capper = User.objects.create_user(
            username="publication-author", role=User.Role.ANALYST
        )
        profile, _ = AnalystProfile.objects.get_or_create(user=capper)
        profile.display_name = "Реальный автор"
        profile.is_public = True
        profile.save()
        article = self.article(author=capper)
        page = self.client.get(article.get_absolute_url())
        self.assertContains(page, 'class="publication-byline"')
        self.assertContains(page, "Реальный автор")
        other = Article.objects.create(
            title="Статья редакции", content="Текст", description="Описание"
        )
        listing = self.client.get(
            reverse("front:articles"), {"author": capper.username}
        )
        self.assertContains(listing, article.title)
        self.assertNotContains(listing, other.title)

    def test_likes_and_bookmarks_toggle_independently(self):
        article = self.article()
        user = User.objects.create_user(username="reactions-reader")
        self.client.force_login(user)
        url = article.get_absolute_url()
        for action in ("like", "bookmark"):
            response = self.client.post(
                url, {"action": action}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["active"])
        state = PublicationReaction.objects.get(user=user)
        self.assertTrue(state.is_liked)
        self.assertTrue(state.is_bookmarked)
        self.client.post(url, {"action": "like"})
        state.refresh_from_db()
        self.assertFalse(state.is_liked)
        self.assertTrue(state.is_bookmarked)

    def test_anonymous_actions_redirect_to_login(self):
        article = self.article()
        response = self.client.post(article.get_absolute_url(), {"action": "like"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("cabinet:login"), response.url)
        self.assertFalse(PublicationReaction.objects.exists())

    def test_comments_and_replies_are_bound_to_publication(self):
        article, other = self.article(), self.article()
        user = User.objects.create_user(username="comment-reader")
        self.client.force_login(user)
        self.client.post(
            article.get_absolute_url(),
            {"action": "comment", "text": "Спасибо за подробный разбор матча"},
        )
        comment = article.publication_comments.get()
        self.assertEqual(comment.user, user)
        self.client.post(
            other.get_absolute_url(),
            {
                "action": "comment",
                "parent_id": comment.pk,
                "text": "Ответ на другой материал",
            },
        )
        self.assertFalse(other.publication_comments.exists())
        self.assertContains(self.client.get(article.get_absolute_url()), comment.text)

    def test_comment_moderation_preserves_rejected_draft(self):
        article = self.article()
        user = User.objects.create_user(username="moderated-reader")
        self.client.force_login(user)
        self.client.post(
            article.get_absolute_url(),
            {"action": "comment", "text": "https://spam.example/test"},
        )
        self.assertFalse(article.publication_comments.exists())
        page = self.client.get(article.get_absolute_url())
        self.assertEqual(
            page.context["publication_comment_draft"], "https://spam.example/test"
        )

    def test_comment_likes_cannot_target_another_article(self):
        article, other = self.article(), self.article()
        user = User.objects.create_user(username="comment-liker")
        comment = Comment.objects.create(user=user, target=other, text="Комментарий")
        self.client.force_login(user)
        self.client.post(
            article.get_absolute_url(),
            {"action": "comment_like", "comment_id": comment.pk},
        )
        self.assertFalse(CommentReaction.objects.exists())

    def test_unpublished_article_rejects_actions(self):
        article = self.article(is_published=False)
        user = User.objects.create_user(username="private-reader")
        self.client.force_login(user)
        self.assertEqual(
            self.client.post(
                article.get_absolute_url(), {"action": "like"}
            ).status_code,
            404,
        )

    def test_comments_page_is_paginated_and_does_not_leak_hidden_comments(self):
        article = self.article()
        user = User.objects.create_user(username="many-comments")
        for index in range(12):
            Comment.objects.create(
                user=user, target=article, text=f"Комментарий {index}"
            )
        Comment.objects.create(
            user=user,
            target=article,
            text="Скрытый комментарий",
            status=Comment.Status.PENDING,
        )
        page = self.client.get(article.get_absolute_url())
        self.assertEqual(len(page.context["publication_comments"]), 10)
        self.assertEqual(page.context["publication_comments_count"], 12)
        self.assertNotContains(page, "Скрытый комментарий")
        self.assertEqual(
            len(
                self.client.get(
                    article.get_absolute_url(), {"comments_page": 2}
                ).context["publication_comments"]
            ),
            2,
        )

    def test_authenticated_actions_require_csrf_token(self):
        article = self.article()
        user = User.objects.create_user(username="csrf-reader")
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        self.assertEqual(
            client.post(article.get_absolute_url(), {"action": "like"}).status_code, 403
        )
        client.get(article.get_absolute_url())
        response = client.post(
            article.get_absolute_url(),
            {
                "action": "like",
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            article.publication_reactions.filter(user=user, is_liked=True).exists()
        )

    def test_prediction_block_honors_free_paid_and_unpublished_access(self):
        from django.contrib.auth.models import AnonymousUser
        from game.models import Match, Prediction, PredictionCoupon

        author = User.objects.create_user(
            username="coupon-author", role=User.Role.ANALYST
        )
        coupon = PredictionCoupon.objects.create(
            author=author,
            published_status="published",
            audience="free",
            total_stake="10",
            possible_payout="18.50",
        )
        match = Match.objects.create(external_id=9938021)
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="totals",
            selection="Тотал меньше 2.5",
            coefficient="1.85",
            stake="10",
        )
        article = self.article(featured_prediction=coupon)
        free = publication_body(article, AnonymousUser())["publication_prediction"]
        self.assertEqual(str(free["coefficient"]), "1.85")
        coupon.audience = "paid"
        coupon.save(update_fields=["audience"])
        article.featured_prediction = coupon
        paid = publication_body(article, AnonymousUser())["publication_prediction"]
        self.assertIsNone(paid["coefficient"])
        self.assertEqual(paid["selection"], "Платный прогноз")
        own = publication_body(article, author)["publication_prediction"]
        self.assertEqual(str(own["coefficient"]), "1.85")
        coupon.published_status = "draft"
        coupon.save(update_fields=["published_status"])
        self.assertIsNone(
            publication_body(article, AnonymousUser())["publication_prediction"]
        )

    def test_body_preserves_table_and_removes_executable_markup(self):
        parsed = PublicationHTML(
            '<script>alert(1)</script><p onclick="alert(1)">Текст</p><table><tr><td>Ячейка</td></tr></table>'
        )
        body = "".join(parsed.fragments)
        self.assertNotIn("alert", body)
        self.assertIn('class="publication-table"', body)
        self.assertIn("<table>", body)
        embed = "".join(
            PublicationHTML(
                '<iframe src="https://www.youtube.com/embed/example" srcdoc="unsafe"></iframe>'
            ).fragments
        )
        self.assertIn('src="https://www.youtube.com/embed/example"', embed)
        self.assertNotIn("srcdoc", embed)

    def test_unsafe_related_link_is_rejected(self):
        article = self.article(related_link_url="javascript:alert(1)")
        with self.assertRaises(ValidationError):
            article.clean()


@override_settings(STORAGES=TEST_STORAGES)
class PublicationSlugTests(TestCase):
    def test_cyrillic_title_generates_unique_ascii_slugs_and_updates(self):
        for model in (Article, News):
            with self.subTest(model=model):
                first = model.objects.create(
                    title="Новый разбор матча", description="Описание", content="Текст"
                )
                second = model.objects.create(
                    title=first.title, description="Описание", content="Текст"
                )
                self.assertEqual(first.slug, "novyy-razbor-matcha")
                self.assertEqual(second.slug, first.slug + "-2")
                old_url = first.get_absolute_url()
                first.title = "Обновлённый разбор"
                first.save(update_fields=["title"])
                self.assertEqual(first.slug, "obnovlennyy-razbor")
                first.refresh_from_db()
                self.assertEqual(first.slug, "obnovlennyy-razbor")
                self.assertRedirects(
                    self.client.get(old_url), first.get_absolute_url(), status_code=301
                )

    def test_manual_slug_and_slug_history_are_preserved(self):
        article = Article.objects.create(
            title="Заголовок", slug="custom", description="Описание", content="Текст"
        )
        article.title = "Другой заголовок"
        article.slug = "manually-edited"
        article.save()
        self.assertEqual(article.slug, "manually-edited")
        self.assertTrue(
            PublicationSlug.objects.filter(slug="custom", object_id=article.pk).exists()
        )
        reserved = Article.objects.create(
            title="Custom", description="Описание", content="Текст"
        )
        self.assertEqual(reserved.slug, "custom-2")

    def test_old_slug_does_not_expose_unpublished_news(self):
        news = News.objects.create(
            title="Первая новость", description="Описание", content="Текст"
        )
        old_url = news.get_absolute_url()
        news.title, news.is_published = "Новая новость", False
        news.save()
        self.assertEqual(self.client.get(old_url).status_code, 404)

    def test_reserved_manual_slug_fails_admin_model_validation(self):
        original = Article.objects.create(
            title="Первый", slug="reserved", description="Описание", content="Текст"
        )
        original.title = "Изменённый"
        original.save()
        other = Article(
            title="Другой", slug="reserved", description="Описание", content="Текст"
        )
        with self.assertRaises(ValidationError):
            other.clean()

    def test_non_title_update_does_not_change_slug(self):
        article = Article.objects.create(
            title="Заголовок", slug="original", description="Описание", content="Текст"
        )
        article.title = "Несохранённый заголовок"
        article.views_count = 4
        article.save(update_fields=["views_count"])
        article.refresh_from_db()
        self.assertEqual(article.slug, "original")
        self.assertEqual(article.views_count, 4)

    def test_capper_admin_title_change_updates_slug_with_id_redirect(self):
        user = User.objects.create_user(username="slug-author", role=User.Role.ANALYST)
        AnalystProfile.objects.update_or_create(user=user, defaults={"is_public": True})
        article = CapperArticle.objects.create(
            author=user, title="Первый текст", content="Текст", status="approved"
        )
        old_url = article.get_absolute_url()
        article.title = "Второй текст"
        article.save()
        self.assertEqual(article.slug, "vtoroy-tekst")
        self.assertRedirects(
            self.client.get(old_url), article.get_absolute_url(), status_code=301
        )


@override_settings(STORAGES=TEST_STORAGES)
class PublicationEditorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="editor-author", role=User.Role.ANALYST
        )
        self.vip = patch.object(
            User, "is_vip", new_callable=PropertyMock, return_value=True
        )
        self.vip.start()
        self.addCleanup(self.vip.stop)
        self.client.force_login(self.user)

    def test_optional_fields_are_visible_and_saved_from_cabinet(self):
        page = self.client.get(reverse("cabinet:capper_article_create"))
        self.assertContains(page, 'name="table_of_contents"')
        self.assertContains(page, 'name="related_link_url"')
        self.assertContains(page, 'name="summary"')
        response = self.client.post(
            reverse("cabinet:capper_article_create"),
            {
                "article_action": "draft",
                "title": "Новый разбор",
                "content": "<h2>Раздел</h2><p>Текст статьи</p>",
                "table_of_contents": "Раздел",
                "pull_quote": "Цитата",
                "related_link_url": "/articles/other/",
                "related_link_title": "Другой разбор",
                "related_link_after_paragraph": 1,
                "summary": "Итог",
                "comments_enabled": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        article = CapperArticle.objects.get(author=self.user)
        self.assertEqual(article.table_of_contents, "Раздел")
        self.assertEqual(article.pull_quote, "Цитата")
        self.assertEqual(article.related_link_after_paragraph, 1)
        self.assertEqual(article.summary, "Итог")
        self.assertTrue(article.comments_enabled)
        self.assertEqual(article.inline_image_after_paragraph, 2)

    def test_capper_related_links_only_allow_site_publications(self):
        for value in (
            "https://external.example/article/",
            "//external.example",
            "/cabinet/",
        ):
            form = CapperArticleForm(
                data={
                    "title": "Текст",
                    "content": "<p>Текст</p>",
                    "related_link_url": value,
                },
                user=self.user,
            )
            self.assertFalse(form.is_valid())
            self.assertIn("related_link_url", form.errors)

    def test_optional_images_survive_editing_and_can_be_cleared(self):
        import tempfile
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(MEDIA_ROOT=directory),
        ):
            image = BytesIO()
            Image.new("RGB", (20, 20), "blue").save(image, format="PNG")
            fields = {
                "article_action": "draft",
                "title": "Статья с изображением",
                "content": "<p>Текст</p>",
                "inline_image": SimpleUploadedFile(
                    "inline.png", image.getvalue(), content_type="image/png"
                ),
            }
            response = self.client.post(
                reverse("cabinet:capper_article_create"), fields
            )
            self.assertEqual(response.status_code, 302)
            article = CapperArticle.objects.get(author=self.user)
            original = article.inline_image.name
            fields.pop("inline_image")
            edit_url = reverse("cabinet:capper_article_edit", args=[article.pk])
            self.assertEqual(self.client.post(edit_url, fields).status_code, 302)
            article.refresh_from_db()
            self.assertEqual(article.inline_image.name, original)
            fields["inline_image-clear"] = "on"
            self.assertEqual(self.client.post(edit_url, fields).status_code, 302)
            article.refresh_from_db()
            self.assertFalse(article.inline_image)

    def test_optional_text_goes_through_article_moderation(self):
        from cabinet.services.capper_articles import _validate_article_text

        article = CapperArticle(
            author=self.user,
            title="Статья",
            content="Текст",
            summary="https://external.example/spam",
        )
        with self.assertRaisesMessage(ValidationError, "ссылку"):
            _validate_article_text(article, user=self.user, check_spam=False)

    def test_editor_rejects_another_authors_featured_prediction(self):
        from game.models import PredictionCoupon

        other = User.objects.create_user(
            username="other-coupon-author", role=User.Role.ANALYST
        )
        coupon = PredictionCoupon.objects.create(
            author=other,
            published_status="published",
            total_stake="10",
            possible_payout="18.50",
        )
        form = CapperArticleForm(
            data={
                "title": "Текст",
                "content": "<p>Текст</p>",
                "featured_prediction": coupon.pk,
            },
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("featured_prediction", form.errors)

    def test_admin_forms_expose_optional_fields_and_only_articles_have_author(self):
        from django.contrib.admin.sites import site
        from django.test import RequestFactory

        request = RequestFactory().get("/admin/")
        request.user = User.objects.create_superuser(
            username="publication-admin", email="admin@example.test", password="test"
        )
        for model in (Article, News):
            form = site._registry[model].get_form(request)
            self.assertIn("summary", form.base_fields)
            self.assertIn("table_of_contents", form.base_fields)
            self.assertEqual("author" in form.base_fields, model is Article)
