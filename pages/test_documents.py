from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.models import User
from front.models import StaticPage
from pages.models import PageDocumentCookie, PageDocumentSection, PageSEO


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class LegalDocumentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        StaticPage.objects.update_or_create(slug="user-agreement", defaults={
            "title": "Пользовательское соглашение", "content": "<p>Существующий текст соглашения.</p>",
        })
        call_command("seed_legal_documents", support_email="support@example.test", stdout=StringIO())

    def document(self, path):
        return PageSEO.objects.get(exact_path=path)

    def test_all_four_routes_render_the_shared_design_and_admin_content(self):
        for path in ("/rules/", "/pages/privacy-policy/", "/pages/user-agreement/", "/pages/cookie-policy/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "front/legal_document.html")
                page = response.context["document"]
                self.assertContains(response, page.document_title)
                self.assertContains(response, "data-legal-document")
                for section in page.document_sections.all():
                    self.assertContains(response, f'id="{section.anchor}"')
                    self.assertContains(response, f'href="#{section.anchor}"')
                self.assertContains(response, 'class="legal-mobile-toc"')
                self.assertNotContains(response, 'href="#"')

    def test_seed_matches_the_provided_sections_and_preserves_existing_agreement(self):
        rules = PageSEO.objects.get(route_name="front:rules", exact_path="")
        self.assertEqual(rules.document_sections.count(), 8)
        self.assertEqual(self.document("/pages/privacy-policy/").document_sections.count(), 7)
        cookies = self.document("/pages/cookie-policy/")
        self.assertEqual(cookies.document_sections.count(), 5)
        self.assertEqual(cookies.document_cookies.count(), 4)
        response = self.client.get("/pages/user-agreement/")
        self.assertContains(response, "Существующий текст соглашения.")
        self.assertEqual(rules.document_updated_on, date(2026, 10, 12))
        self.assertEqual(rules.document_revision, "2.1")

    def test_admin_edits_are_visible_immediately_without_template_edits(self):
        self.client.get("/pages/privacy-policy/")
        page = self.document("/pages/privacy-policy/")
        page.document_title = "Новое название из админки"
        page.document_subtitle = "Описание из админки"
        page.document_labels = {"contents": "Разделы политики"}
        page.save()
        section = page.document_sections.first()
        section.content = '<p>Новый текст</p><div class="legal-note is-info">Примечание</div>'
        section.save()
        response = self.client.get("/pages/privacy-policy/")
        for text in (page.document_title, page.document_subtitle, "Разделы политики", "Новый текст", "legal-note is-info"):
            self.assertContains(response, text)

    def test_hidden_sections_and_unpublished_related_documents_are_not_rendered(self):
        page = self.document("/pages/privacy-policy/")
        section = page.document_sections.first()
        section.is_active = False
        section.save()
        cookie_page = self.document("/pages/cookie-policy/")
        cookie_page.is_active = False
        cookie_page.save()
        response = self.client.get("/pages/privacy-policy/")
        self.assertNotContains(response, f'id="{section.anchor}"')
        self.assertNotIn("/pages/cookie-policy/", [item["url"] for item in response.context["document_related"]])

    def test_pdf_button_requires_an_uploaded_file(self):
        response = self.client.get("/pages/privacy-policy/")
        self.assertNotContains(response, "Скачать PDF")
        page = self.document("/pages/privacy-policy/")
        page.document_pdf = "documents/policy.pdf"
        page.save()
        response = self.client.get("/pages/privacy-policy/")
        self.assertContains(response, "Скачать PDF")
        self.assertContains(response, 'href="/media/documents/policy.pdf" download')

    def test_cookie_controls_work_for_anonymous_and_authenticated_visitors(self):
        reader = User.objects.create_user(username="cookie-reader")
        for authenticated in (False, True):
            if authenticated:
                self.client.force_login(reader)
            response = self.client.get("/pages/cookie-policy/")
            self.assertContains(response, 'data-document-cookie="analytics"')
            self.assertContains(response, "data-document-cookie-save")
            self.assertContains(response, "data-cookie-preferences")
            self.assertContains(response, "data-cookie-settings")
            self.assertContains(response, "legal-cookie-switch")

    def test_generic_static_page_seo_does_not_replace_exact_document_settings(self):
        PageSEO.objects.update_or_create(route_name="front:static_page", exact_path="", defaults={
            "name": "Общие настройки", "document_enabled": True, "document_title": "Общее название",
        })
        response = self.client.get("/pages/privacy-policy/")
        self.assertContains(response, "Политика конфиденциальности")
        self.assertNotContains(response, "Общее название")

    def test_normal_static_pages_keep_the_existing_layout(self):
        StaticPage.objects.create(title="Справка", slug="other-document", content="<p>Другой документ</p>")
        response = self.client.get("/pages/other-document/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "front/static_page.html")

    def test_seed_is_idempotent_and_force_is_explicit(self):
        page = self.document("/pages/privacy-policy/")
        section = page.document_sections.first()
        section.content = "<p>Ручная правка администратора</p>"
        section.save()
        page.meta_title = "Собственное SEO"
        page.save()
        counts = (PageSEO.objects.count(), PageDocumentSection.objects.count(), PageDocumentCookie.objects.count())
        call_command("seed_legal_documents", stdout=StringIO())
        section.refresh_from_db()
        self.assertIn("Ручная правка", section.content)
        self.assertEqual(counts, (PageSEO.objects.count(), PageDocumentSection.objects.count(), PageDocumentCookie.objects.count()))
        call_command("seed_legal_documents", force=True, stdout=StringIO())
        page.refresh_from_db()
        self.assertEqual(page.meta_title, "Собственное SEO")
        self.assertNotIn("Ручная правка", page.document_sections.first().content)

    def test_seed_dry_run_makes_no_changes(self):
        PageSEO.objects.filter(document_enabled=True).delete()
        count = PageSEO.objects.count()
        output = StringIO()
        call_command("seed_legal_documents", dry_run=True, stdout=output)
        self.assertEqual(PageSEO.objects.count(), count)
        self.assertEqual(PageDocumentSection.objects.count(), 0)
        self.assertIn("Данные не изменены", output.getvalue())

    def test_rules_seed_uses_existing_exact_path_override(self):
        PageSEO.objects.filter(route_name="front:rules").delete()
        page = PageSEO.objects.create(route_name="front:rules", exact_path="/rules/", name="Правила")
        call_command("seed_legal_documents", stdout=StringIO())
        page.refresh_from_db()
        self.assertTrue(page.document_enabled)
        self.assertEqual(PageSEO.objects.filter(route_name="front:rules").count(), 1)
        self.assertTemplateUsed(self.client.get("/rules/"), "front/legal_document.html")

    def test_document_editor_is_available_inside_seo_admin(self):
        staff = User.objects.create_superuser(username="documents-admin", email="staff@example.test", password="test")
        self.client.force_login(staff)
        page = self.document("/pages/privacy-policy/")
        response = self.client.get(reverse("admin:pages_pageseo_change", args=[page.pk]))
        self.assertEqual(response.status_code, 200)
        for name in ("document_title", "document_revision", "document_support_url", "document_sections-0-title"):
            self.assertContains(response, f'name="{name}"')
