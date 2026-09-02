from django.test import TestCase
from django.urls import reverse

from .models import HelpAccordionItem, HelpBlock


class HelpContentViewTests(TestCase):
    def setUp(self):
        self.help_block = HelpBlock.objects.create(
            key="test-help",
            title="Тестовая помощь",
            is_active=True,
        )
        HelpAccordionItem.objects.create(
            help_block=self.help_block,
            title="Первый вопрос",
            content="<p><strong>Ответ</strong> из RichText.</p>",
            sort_order=10,
            is_active=True,
        )
        HelpAccordionItem.objects.create(
            help_block=self.help_block,
            title="Скрытый вопрос",
            content="<p>Не должен попасть в ответ.</p>",
            sort_order=20,
            is_active=False,
        )

    def test_help_content_is_loaded_as_server_rendered_html(self):
        response = self.client.get(reverse("pages:help_content", args=[self.help_block.key]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["title"], "Тестовая помощь")
        self.assertIn("Первый вопрос", payload["html"])
        self.assertIn("<strong>Ответ</strong>", payload["html"])
        self.assertNotIn("Скрытый вопрос", payload["html"])
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_disabled_help_block_returns_404(self):
        self.help_block.is_active = False
        self.help_block.save(update_fields=["is_active", "updated_at"])

        response = self.client.get(reverse("pages:help_content", args=[self.help_block.key]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["ok"])
