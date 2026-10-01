from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0057_remove_vipplan_price_coins"),
    ]

    operations = [
        migrations.CreateModel(
            name="VipPlanComparisonFeature",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160, verbose_name="Название")),
                (
                    "icon",
                    models.ImageField(
                        blank=True,
                        upload_to="vip_plans/comparison/icons/%Y/%m/",
                        verbose_name="Иконка",
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активна")),
                ("order", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создана")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлена")),
            ],
            options={
                "verbose_name": "Строка сравнения VIP",
                "verbose_name_plural": "Строки сравнения VIP",
                "ordering": ("order", "id"),
            },
        ),
        migrations.CreateModel(
            name="VipPlanComparisonValue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value_text", models.CharField(blank=True, max_length=160, verbose_name="Текст")),
                ("is_checked", models.BooleanField(default=False, verbose_name="Показать галочку")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "feature",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="values",
                        to="cabinet.vipplancomparisonfeature",
                        verbose_name="Строка сравнения",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comparison_values",
                        to="cabinet.vipplan",
                        verbose_name="VIP-тариф",
                    ),
                ),
            ],
            options={
                "verbose_name": "Значение сравнения VIP",
                "verbose_name_plural": "Значения сравнения VIP",
                "ordering": ("feature__order", "feature_id", "plan__order", "plan_id"),
            },
        ),
        migrations.AddConstraint(
            model_name="vipplancomparisonvalue",
            constraint=models.UniqueConstraint(
                fields=("feature", "plan"),
                name="unique_vip_plan_comparison_value",
            ),
        ),
    ]
