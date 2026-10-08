import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0012_about_page_seo"),
    ]

    operations = [
        migrations.AddField(
            model_name="pageseo",
            name="home_top_experts_limit",
            field=models.PositiveSmallIntegerField(
                default=4,
                help_text=(
                    "Сколько экспертов показывать в блоке «Топовые эксперты месяца» "
                    "на главной странице. Используется только для route_name='front:index'."
                ),
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(50),
                ],
                verbose_name="Топовые эксперты на главной",
            ),
        ),
    ]
