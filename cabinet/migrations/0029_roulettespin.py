import uuid

from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0028_userroulettestate"),
    ]

    operations = [
        migrations.CreateModel(
            name="RouletteSpin",
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
                    "operation_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                        verbose_name="ID операции",
                    ),
                ),
                (
                    "spun_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        verbose_name="Время прокрутки",
                    ),
                ),
                ("attempts_before", models.PositiveIntegerField(default=0, verbose_name="Попыток до")),
                ("attempts_after", models.PositiveIntegerField(default=0, verbose_name="Попыток после")),
                (
                    "next_spin_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Следующая ежедневная попытка",
                    ),
                ),
                (
                    "prize_title",
                    models.CharField(max_length=80, verbose_name="Название приза на момент выигрыша"),
                ),
                (
                    "prize_short_text",
                    models.CharField(
                        blank=True,
                        max_length=140,
                        verbose_name="Подпись приза на момент выигрыша",
                    ),
                ),
                (
                    "prize_icon",
                    models.CharField(
                        blank=True,
                        help_text="Путь к файлу иконки на момент прокрутки.",
                        max_length=500,
                        verbose_name="Иконка приза на момент выигрыша",
                    ),
                ),
                (
                    "prize_sector_order",
                    models.PositiveSmallIntegerField(
                        default=0,
                        verbose_name="Позиция сектора на момент выигрыша",
                    ),
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
                        max_length=32,
                        verbose_name="Тип награды на момент выигрыша",
                    ),
                ),
                (
                    "reward_value",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=12,
                        verbose_name="Значение награды на момент выигрыша",
                    ),
                ),
                (
                    "reward_text",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="Текст награды на момент выигрыша",
                    ),
                ),
                (
                    "reward_status",
                    models.CharField(
                        choices=[
                            ("pending", "Ожидает выдачи"),
                            ("issued", "Выдано"),
                            ("failed", "Ошибка выдачи"),
                            ("not_required", "Выдача не требуется"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                        verbose_name="Статус выдачи",
                    ),
                ),
                (
                    "issued_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Выдано",
                    ),
                ),
                ("issue_error", models.CharField(blank=True, max_length=500, verbose_name="Ошибка выдачи")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "prize",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="spins",
                        to="cabinet.rouletteprize",
                        verbose_name="Приз",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="roulette_spins",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Прокрутка рулетки",
                "verbose_name_plural": "История прокруток рулетки",
                "ordering": ("-spun_at", "-id"),
                "indexes": [
                    models.Index(fields=["user", "spun_at"], name="roulette_spin_user_time_idx"),
                    models.Index(fields=["prize", "spun_at"], name="roulette_spin_prize_time_idx"),
                    models.Index(fields=["reward_status", "spun_at"], name="roulette_spin_status_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("attempts_before__gte", 0)),
                        name="roulette_spin_before_nonneg",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("attempts_after__gte", 0)),
                        name="roulette_spin_after_nonneg",
                    ),
                ],
            },
        ),
    ]
