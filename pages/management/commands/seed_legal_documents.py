import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from back.models import WebsiteSettings
from front.models import StaticPage
from pages.models import PageDocumentCookie, PageDocumentSection, PageSEO


class Command(BaseCommand):
    help = "Заполняет дизайн документов в SEO Pages по Django view name и точному пути."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Заменить ранее заполненные разделы данными макетов.")
        parser.add_argument("--dry-run", action="store_true", help="Показать страницы без записи в БД.")
        parser.add_argument("--support-email", default="", help="Email для кнопки поддержки; иначе берётся email футера.")

    @transaction.atomic
    def handle(self, *args, **options):
        data_path = Path(__file__).resolve().parents[2] / "seed_data/legal_documents.json"
        documents = json.loads(data_path.read_text())
        agreement = StaticPage.objects.filter(slug="user-agreement").first() or StaticPage.objects.filter(slug="terms").first()
        documents.append({
            "key": "agreement", "route_name": "front:static_page", "exact_path": "/pages/user-agreement/",
            "path": "/pages/user-agreement/", "document_title": "Пользовательское соглашение",
            "document_icon": "document", "document_subtitle": "", "document_revision": "",
            "document_updated_on": timezone.localtime(agreement.updated_at).date() if agreement else None,
            "document_support_title": documents[0]["document_support_title"],
            "document_support_text": documents[0]["document_support_text"],
            "document_support_button": documents[0]["document_support_button"],
            "related": ["rules", "privacy", "cookies"], "cookies": [],
            "sections": [{"title": "Пользовательское соглашение", "anchor": "agreement-01", "kind": "content",
                          "sort_order": 10, "content": agreement.content if agreement else ""}],
        })
        support_email = options["support_email"] or (
            WebsiteSettings.objects.order_by("pk").values_list("footer_support_email", flat=True).first() or settings.SUPPORT_EMAIL
        )
        pages_by_key = {}
        changed = []
        for item in documents:
            lookup = {"route_name": item["route_name"], "exact_path": item["exact_path"]}
            page = None
            if item["key"] == "rules":
                page = PageSEO.objects.filter(route_name=item["route_name"], exact_path=item["path"]).first()
            page = page or PageSEO.objects.filter(**lookup).first()
            if options["dry_run"]:
                action = "Пропуск" if page and page.document_title and not options["force"] else "Заполнение"
                self.stdout.write(f"{action}: {item['route_name']} · {item['path']}")
                continue
            if page is None:
                page = PageSEO.objects.create(
                    **lookup, name=item["document_title"], meta_title=f"{item['document_title']} — КапперХаб",
                    meta_description=item["document_subtitle"], layout_columns=PageSEO.LayoutColumns.CENTER_ONLY,
                )
            pages_by_key[item["key"]] = page
            if page.document_title and not options["force"]:
                self.stdout.write(f"Сохранён существующий контент: {page}")
                continue
            for name, value in item.items():
                if name.startswith("document_"):
                    setattr(page, name, value)
            page.document_enabled = True
            page.document_support_url = f"mailto:{support_email}" if support_email else ""
            page.save()
            page.document_sections.all().delete()
            page.document_cookies.all().delete()
            for section in item["sections"]:
                PageDocumentSection.objects.create(page=page, **section)
            for category in item["cookies"]:
                PageDocumentCookie.objects.create(page=page, **category)
            changed.append(item)
            self.stdout.write(self.style.SUCCESS(f"Заполнено: {page.route_name} · {item['path']}"))
        for item in changed:
            pages_by_key[item["key"]].document_related_pages.set([pages_by_key[key] for key in item["related"]])
        if options["dry_run"]:
            self.stdout.write("Проверка завершена. Данные не изменены.")
