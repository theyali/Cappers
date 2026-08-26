from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0002_move_website_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_enabled",
            field=models.BooleanField(default=True, verbose_name="Показывать блок «О нас» на главной"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_eyebrow",
            field=models.CharField(blank=True, default="О компании", max_length=80, verbose_name="Надпись над заголовком"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_title",
            field=models.CharField(blank=True, default="КапперХаб — спортивная аналитика в одном месте", max_length=220, verbose_name="Заголовок блока"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_intro",
            field=models.TextField(blank=True, default="Мы собираем матчи, статистику, экспертные материалы и спортивный контент в одном понятном интерфейсе.", verbose_name="Короткое описание"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_text",
            field=models.TextField(blank=True, default="КапперХаб — информационная платформа для аудитории, которая следит за спортом и хочет быстрее находить данные, мнения авторов и разборы матчей. Мы развиваем публичные профили экспертов, ленты материалов, рейтинги и удобные страницы матчей, чтобы важная информация была доступна в одном месте.", verbose_name="Основной текст о компании"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_seo_title",
            field=models.CharField(blank=True, default="Спортивные матчи, аналитика, эксперты и статьи", max_length=220, verbose_name="SEO-заголовок внутри блока"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_seo_text",
            field=models.TextField(blank=True, default="На КапперХаб можно изучать расписание и карточки спортивных матчей, читать аналитические материалы, сравнивать публичные профили авторов и следить за обновлениями спортивной ленты. Структура сайта помогает быстро переходить между матчами, экспертами, статистикой и статьями.", verbose_name="SEO-текст на главной"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_fact_1_title",
            field=models.CharField(blank=True, default="Матчи и данные", max_length=80, verbose_name="Карточка 1 — заголовок"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_fact_1_text",
            field=models.CharField(blank=True, default="Расписание, статусы матчей и ключевая информация в одном интерфейсе.", max_length=220, verbose_name="Карточка 1 — текст"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_fact_2_title",
            field=models.CharField(blank=True, default="Публичные эксперты", max_length=80, verbose_name="Карточка 2 — заголовок"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_fact_2_text",
            field=models.CharField(blank=True, default="Профили авторов, статистика активности, достижения и подписки.", max_length=220, verbose_name="Карточка 2 — текст"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_fact_3_title",
            field=models.CharField(blank=True, default="Спортивный контент", max_length=80, verbose_name="Карточка 3 — заголовок"),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="home_about_fact_3_text",
            field=models.CharField(blank=True, default="Статьи, разборы и материалы редакции для спортивной аудитории.", max_length=220, verbose_name="Карточка 3 — текст"),
        ),
    ]
