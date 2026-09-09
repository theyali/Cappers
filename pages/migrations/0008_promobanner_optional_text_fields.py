from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0007_promobanner_pageseo_promo_banners"),
    ]

    operations = [
        migrations.AlterField(
            model_name="promobanner",
            name="name",
            field=models.CharField(
                blank=True,
                max_length=160,
                verbose_name="Название в админке",
            ),
        ),
        migrations.AlterField(
            model_name="promobanner",
            name="title",
            field=models.CharField(
                blank=True,
                max_length=180,
                verbose_name="Title",
            ),
        ),
        migrations.AlterField(
            model_name="promobanner",
            name="button_label",
            field=models.CharField(
                blank=True,
                max_length=80,
                verbose_name="Текст кнопки",
            ),
        ),
        migrations.AlterField(
            model_name="promobanner",
            name="button_url",
            field=models.CharField(
                help_text=(
                    "Для баннера только с изображением ссылка открывается по клику на весь баннер. "
                    "Для старого текстового варианта используется как ссылка кнопки. Можно указать "
                    "относительный путь, например /tournaments/, или полный URL."
                ),
                max_length=1000,
                verbose_name="Ссылка",
            ),
        ),
    ]
