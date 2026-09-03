from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum
import django.db.models.deletion


def backfill_capper_bank_stats(apps, schema_editor):
    User = apps.get_model("cabinet", "User")
    PredictionCoupon = apps.get_model("game", "PredictionCoupon")
    CapperBankStats = apps.get_model("wallets", "CapperBankStats")
    db_alias = schema_editor.connection.alias
    zero = Decimal("0")
    settled_states = ("win", "lose", "refund")

    user_ids = (
        User.objects.using(db_alias)
        .filter(role="analyst")
        .values_list("id", flat=True)
        .iterator()
    )
    for user_id in user_ids:
        published = PredictionCoupon.objects.using(db_alias).filter(
            author_id=user_id,
            published_status="published",
        )
        win_profit = ExpressionWrapper(
            F("possible_payout") - F("total_stake"),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
        values = published.aggregate(
            coupons_count=Count("id"),
            stake_sum=Sum("total_stake"),
            average_stake=Avg("total_stake"),
            lost_amount=Sum("total_stake", filter=Q(state_status="lose")),
            earned_amount=Sum(win_profit, filter=Q(state_status="win")),
            pending_stake=Sum("total_stake", filter=Q(state_status="pending")),
            settled_count=Count("id", filter=Q(state_status__in=settled_states)),
        )
        total_stake = values["stake_sum"] or zero
        average_stake = values["average_stake"] or zero
        lost_amount = values["lost_amount"] or zero
        earned_amount = values["earned_amount"] or zero
        pending_stake = values["pending_stake"] or zero

        CapperBankStats.objects.using(db_alias).update_or_create(
            user_id=user_id,
            defaults={
                "coupons_count": values["coupons_count"] or 0,
                "settled_count": values["settled_count"] or 0,
                "total_stake": total_stake,
                "average_stake": average_stake,
                "lost_amount": lost_amount,
                "earned_amount": earned_amount,
                "pending_stake": pending_stake,
                "net_result": earned_amount - lost_amount,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0019_predictioncoupon_is_paid"),
        ("wallets", "0003_copybettingsubscription_allowed_sports_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CapperBankStats",
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
                ("coupons_count", models.PositiveIntegerField(default=0, verbose_name="Опубликовано купонов")),
                ("settled_count", models.PositiveIntegerField(default=0, verbose_name="Рассчитано купонов")),
                ("total_stake", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Сыграно за всё время")),
                ("average_stake", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Средняя ставка")),
                ("lost_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Проиграно")),
                ("earned_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Заработано")),
                ("pending_stake", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Сейчас в игре")),
                ("net_result", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Чистый результат")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создана")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлена")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="public_bank_stats",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Каппер",
                    ),
                ),
            ],
            options={
                "verbose_name": "Публичный банк каппера",
                "verbose_name_plural": "Публичные банки капперов",
                "ordering": ["user_id"],
            },
        ),
        migrations.RunPython(backfill_capper_bank_stats, migrations.RunPython.noop),
    ]
