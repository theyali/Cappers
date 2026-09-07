from django.db import migrations, models
import django.db.models.deletion


def seed_footer_content(apps, schema_editor):
    WebsiteSettings = apps.get_model("back", "WebsiteSettings")
    FooterLinkGroup = apps.get_model("back", "FooterLinkGroup")
    FooterLink = apps.get_model("back", "FooterLink")
    FooterButton = apps.get_model("back", "FooterButton")

    settings, _ = WebsiteSettings.objects.get_or_create(pk=1)
    settings.footer_support_title = settings.footer_support_title or "Поддержка 24/7"
    settings.footer_support_email = settings.footer_support_email or "support@capperhub.ru"
    settings.footer_legal_text = settings.footer_legal_text or "Официальные документы сервиса"
    settings.footer_address_text = settings.footer_address_text or "КапперХаб — информационная платформа о спортивной аналитике."
    settings.save()

    groups = (
        (
            "Разделы",
            10,
            (
                ("Матчи", "/matches/", 10),
                ("Все прогнозы", "/predictions/", 20),
                ("Турниры", "/tournaments/", 30),
                ("Капперы", "/cappers-statistics/", 40),
                ("Статьи", "/articles/", 50),
            ),
        ),
        (
            "Сервис",
            20,
            (
                ("Как пользоваться", "/how-it-works/", 10),
                ("Стать каппером", "/cabinet/become-capper/", 20),
                ("Бонусы", "/bonuses/", 30),
                ("Букмекеры", "/bookmakers/", 40),
            ),
        ),
        (
            "Документы",
            30,
            (
                ("Политика конфиденциальности", "/pages/privacy-policy/", 10),
                ("Пользовательское соглашение", "/pages/user-agreement/", 20),
                ("Политика cookies", "/pages/cookie-policy/", 30),
            ),
        ),
    )
    for title, order, links in groups:
        group, _ = FooterLinkGroup.objects.get_or_create(
            title=title,
            defaults={"order": order, "is_active": True},
        )
        for link_title, url, link_order in links:
            FooterLink.objects.get_or_create(
                group=group,
                title=link_title,
                defaults={"url": url, "order": link_order, "is_active": True},
            )

    buttons = (
        ("app", "для iOS", "Приложение", "", "iOS", 10),
        ("app", "для Android", "Приложение", "", "A", 20),
        ("social", "Вконтакте", "", "#", "VK", 10),
        ("social", "Telegram", "", "#", "TG", 20),
        ("social", "YouTube", "", "#", "YT", 30),
        ("partner", "Партнёр 1", "", "#", "P1", 10),
        ("partner", "Партнёр 2", "", "#", "P2", 20),
        ("partner", "Партнёр 3", "", "#", "P3", 30),
    )
    for kind, title, subtitle, url, icon_text, order in buttons:
        FooterButton.objects.get_or_create(
            kind=kind,
            title=title,
            defaults={
                "subtitle": subtitle,
                "url": url,
                "icon_text": icon_text,
                "order": order,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0009_website_referral_and_fee_percentages"),
    ]

    operations = [
        migrations.CreateModel(
            name="FooterButton",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("app", "Приложение"), ("social", "Соцсеть"), ("partner", "Партнёр/логотип")], db_index=True, max_length=16, verbose_name="Тип")),
                ("title", models.CharField(max_length=120, verbose_name="Текст")),
                ("subtitle", models.CharField(blank=True, max_length=120, verbose_name="Подпись")),
                ("url", models.CharField(blank=True, max_length=500, verbose_name="Ссылка")),
                ("icon_text", models.CharField(blank=True, max_length=16, verbose_name="Текстовая иконка")),
                ("icon", models.ImageField(blank=True, upload_to="footer/", verbose_name="Иконка")),
                ("order", models.PositiveIntegerField(db_index=True, default=0, verbose_name="Порядок")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активен")),
            ],
            options={
                "verbose_name": "Футер — кнопка/логотип",
                "verbose_name_plural": "Футер — кнопки и логотипы",
                "ordering": ("kind", "order", "id"),
            },
        ),
        migrations.CreateModel(
            name="FooterLinkGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120, verbose_name="Заголовок")),
                ("order", models.PositiveIntegerField(db_index=True, default=0, verbose_name="Порядок")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активна")),
            ],
            options={
                "verbose_name": "Футер — группа ссылок",
                "verbose_name_plural": "Футер — группы ссылок",
                "ordering": ("order", "id"),
            },
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_address_text",
            field=models.TextField(blank=True, verbose_name="Футер — адрес/реквизиты"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_age_label",
            field=models.CharField(blank=True, default="18+", max_length=16, verbose_name="Футер — возрастной знак"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_copyright_text",
            field=models.CharField(blank=True, default="© КапперХаб. Все права защищены.", max_length=220, verbose_name="Футер — копирайт"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_description",
            field=models.TextField(blank=True, default="Прогнозы на спорт, статистика капперов и история результатов в одном месте.", verbose_name="Футер — описание"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_disclaimer_text",
            field=models.CharField(blank=True, default="Сервис не гарантирует результат спортивных прогнозов.", max_length=260, verbose_name="Футер — дисклеймер"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_legal_text",
            field=models.TextField(blank=True, default="Официальные документы сервиса", verbose_name="Футер — юридический текст"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_responsible_text",
            field=models.TextField(blank=True, default="Материалы сайта носят информационный характер. Оценивайте риски и принимайте решения самостоятельно.", verbose_name="Футер — предупреждение"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_support_email",
            field=models.EmailField(blank=True, max_length=254, verbose_name="Футер — email поддержки"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_support_phone",
            field=models.CharField(blank=True, max_length=80, verbose_name="Футер — телефон поддержки"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="footer_support_title",
            field=models.CharField(blank=True, default="Поддержка 24/7", max_length=120, verbose_name="Футер — заголовок поддержки"),
        ),
        migrations.CreateModel(
            name="FooterLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160, verbose_name="Текст")),
                ("url", models.CharField(max_length=500, verbose_name="Ссылка")),
                ("order", models.PositiveIntegerField(db_index=True, default=0, verbose_name="Порядок")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активна")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="links", to="back.footerlinkgroup", verbose_name="Группа")),
            ],
            options={
                "verbose_name": "Футер — ссылка",
                "verbose_name_plural": "Футер — ссылки",
                "ordering": ("group__order", "order", "id"),
            },
        ),
        migrations.RunPython(seed_footer_content, migrations.RunPython.noop),
    ]
