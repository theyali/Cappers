from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse


class HomeAboutUiTests(SimpleTestCase):
    def test_home_about_renders_logo_and_capper_benefits(self):
        request = RequestFactory().get("/")
        request.user = SimpleNamespace(is_authenticated=False, is_analyst=False)
        website_settings = SimpleNamespace(
            site_name="КапперХаб",
            home_about_title="О платформе",
            home_about_lead="Прозрачная статистика прогнозов.",
            home_about_text="Короткое описание проекта.",
        )

        html = render_to_string(
            "front/includes/_home_about.html",
            {"website_settings": website_settings},
            request=request,
        )

        self.assertIn("front/img/logo.png", html)
        self.assertIn("Автоматическая статистика", html)
        self.assertIn("Рейтинг по результатам", html)
        self.assertIn("Подписчики и личная лента", html)
        self.assertIn("Публичный профиль", html)
        self.assertIn(reverse("cabinet:become_capper"), html)
