from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0058_vip_plan_comparison"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="mobile_quick_access",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Список ключей страниц, которые показываются в быстром доступе мобильного меню.",
                verbose_name="Быстрый доступ в мобильном меню",
            ),
        ),
    ]
