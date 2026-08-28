from django.template import Context, Template
from django.test import TestCase

from back.models import Bookmaker


class HomeBookmakersTests(TestCase):
    def setUp(self):
        self.hidden = Bookmaker.objects.create(
            name="Hidden BK",
            link="https://example.com/hidden",
            description="Не должен попадать на главную.",
            show_on_home=False,
            home_order=0,
            order=0,
        )
        self.second = Bookmaker.objects.create(
            name="Second BK",
            link="https://example.com/second",
            description="Второй по порядку на главной.",
            show_on_home=True,
            home_order=20,
            order=0,
        )
        self.first = Bookmaker.objects.create(
            name="First BK",
            link="https://example.com/first",
            description="Первый по отдельной сортировке главной.",
            bonus_text="Забрать бонус",
            show_on_home=True,
            home_order=10,
            order=999,
        )

    def test_home_bookmakers_filters_and_uses_home_order(self):
        html = Template("{% load site_extras %}{% home_bookmakers %}").render(Context())

        self.assertNotIn(self.hidden.name, html)
        self.assertIn(self.first.description, html)
        self.assertIn(self.second.description, html)
        self.assertLess(html.index(self.first.name), html.index(self.second.name))
