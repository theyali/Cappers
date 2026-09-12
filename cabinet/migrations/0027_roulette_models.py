import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0026_analystprofile_x"),
    ]

    operations = [
        migrations.CreateModel(
            name="RouletteSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("is_enabled", models.BooleanField(default=True, verbose_name="Рулетка включена")),
                (
                    "daily_free_spins",
                    models.PositiveSmallIntegerField(
                        default=1,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                        verbose_name="Бесплатных попыток в день",
                    ),
                ),
                (
                    "reset_hour",
                    models.PositiveSmallIntegerField(
                        default=0,
                        help_text="Час по часовому поясу проекта, когда становятся доступны ежедневные попытки.",
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(23),
                        ],
                        verbose_name="Час ежедневного обновления",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
            ],
            options={
                "verbose_name": "Настройки рулетки",
                "verbose_name_plural": "Настройки рулетки",
            },
        ),
        migrations.CreateModel(
            name="RoulettePrize",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=80, verbose_name="Название")),
                ("short_text", models.CharField(blank=True, max_length=140, verbose_name="Короткий текст")),
                (
                    "icon",
                    models.ImageField(
                        blank=True,
                        upload_to="roulette/prizes/%Y/%m/",
                        verbose_name="Иконка",
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активен")),
                (
                    "sector_order",
                    models.PositiveSmallIntegerField(db_index=True, default=0, verbose_name="Порядок сектора"),
                ),
                (
                    "reward_type",
                    models.CharField(
                        choices=[
                            ("virtual_balance", "Виртуальный баланс"),
                            ("vip_days", "VIP на несколько дней"),
                            ("free_predictions", "Бесплатные прогнозы"),
                            ("promo_code", "Промокод"),
                            ("rating_boost", "Буст рейтинга"),
                            ("extra_spin", "Дополнительная попытка"),
                            ("nothing", "Пустой сектор"),
                        ],
                        db_index=True,
                        max_length=32,
                        verbose_name="Тип награды",
                    ),
                ),
                (
                    "reward_value",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text="Сумма, количество дней, прогнозов, попыток или размер буста — зависит от типа награды.",
                        max_digits=12,
                        verbose_name="Величина награды",
                    ),
                ),
                (
                    "reward_text",
                    models.CharField(
                        blank=True,
                        help_text="Например, сам промокод. Не используется для выполнения произвольного кода.",
                        max_length=255,
                        verbose_name="Текстовое значение награды",
                    ),
                ),
                (
                    "weight",
                    models.PositiveIntegerField(
                        default=1,
                        help_text="Относительный вес. Чем больше значение, тем чаще сектор может выпадать.",
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Вес выпадения",
                    ),
                ),
                ("active_from", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Активен с")),
                ("active_until", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Активен до")),
                (
                    "total_award_limit",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Пусто — без общего лимита.",
                        null=True,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Общий лимит выдач",
                    ),
                ),
                (
                    "per_user_award_limit",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Пусто — без лимита на пользователя.",
                        null=True,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Лимит на пользователя",
                    ),
                ),
                (
                    "daily_award_limit",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Пусто — без дневного лимита.",
                        null=True,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Дневной лимит выдач",
                    ),
                ),
                (
                    "condition_logic",
                    models.CharField(
                        choices=[("all", "Все условия"), ("any", "Хотя бы одно условие")],
                        default="all",
                        max_length=8,
                        verbose_name="Как применять условия",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлён")),
            ],
            options={
                "verbose_name": "Приз рулетки",
                "verbose_name_plural": "Призы рулетки",
                "ordering": ("sector_order", "id"),
                "indexes": [
                    models.Index(fields=["is_active", "sector_order"], name="roulette_prize_active_order_idx"),
                    models.Index(fields=["is_active", "active_from", "active_until"], name="roulette_prize_period_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("reward_value__gte", 0)),
                        name="roulette_prize_value_non_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("weight__gt", 0)),
                        name="roulette_prize_weight_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("total_award_limit__isnull", True), ("total_award_limit__gt", 0), _connector="OR"),
                        name="roulette_prize_total_limit_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("per_user_award_limit__isnull", True), ("per_user_award_limit__gt", 0), _connector="OR"),
                        name="roulette_prize_user_limit_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("daily_award_limit__isnull", True), ("daily_award_limit__gt", 0), _connector="OR"),
                        name="roulette_prize_daily_limit_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("active_from__isnull", True),
                            ("active_until__isnull", True),
                            ("active_until__gt", models.F("active_from")),
                            _connector="OR",
                        ),
                        name="roulette_prize_valid_period",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RoulettePrizeCondition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "condition_type",
                    models.CharField(
                        choices=[
                            ("all_users", "Все пользователи"),
                            ("readers_only", "Только обычные пользователи"),
                            ("analysts_only", "Только капперы"),
                            ("without_vip", "Только без VIP"),
                            ("min_account_age_days", "Минимальный возраст аккаунта"),
                            ("min_activity_count", "Минимальная активность"),
                        ],
                        max_length=32,
                        verbose_name="Условие",
                    ),
                ),
                (
                    "threshold",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Используется только для числовых условий: возраст аккаунта или активность.",
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Порог",
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активно")),
                ("order", models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "prize",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conditions",
                        to="cabinet.rouletteprize",
                        verbose_name="Приз",
                    ),
                ),
            ],
            options={
                "verbose_name": "Условие приза рулетки",
                "verbose_name_plural": "Условия призов рулетки",
                "ordering": ("order", "id"),
                "indexes": [
                    models.Index(fields=["prize", "is_active", "order"], name="roulette_condition_active_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("prize", "condition_type"),
                        name="unique_roulette_prize_condition_type",
                    ),
                ],
            },
        ),
    ]
