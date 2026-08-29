from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


PERCENT_STEP = Decimal("0.01")
MONEY_STEP = Decimal("0.01")


def _local(value):
    if value is not None and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def _percent(numerator, denominator):
    if not denominator or denominator <= 0:
        return Decimal("0")
    return (numerator / denominator * Decimal("100")).quantize(
        PERCENT_STEP,
        rounding=ROUND_HALF_UP,
    )


def backfill_monthly_stats(apps, schema_editor):
    Coupon = apps.get_model("game", "PredictionCoupon")
    MonthlyStat = apps.get_model("cabinet", "CapperMonthlyStat")

    groups = defaultdict(
        lambda: {
            "bets": 0,
            "wins": 0,
            "losses": 0,
            "refunds": 0,
            "stake": Decimal("0"),
            "profit": Decimal("0"),
            "flat_units": Decimal("0"),
            "coefficient_sum": Decimal("0"),
            "coefficient_count": 0,
        }
    )

    rows = (
        Coupon.objects.filter(
            published_status="published",
            state_status__in=("win", "lose", "refund"),
        )
        .values_list(
            "author_id",
            "state_status",
            "total_stake",
            "possible_payout",
            "settled_at",
            "updated_at",
            "published_at",
            "created_at",
        )
        .iterator(chunk_size=2000)
    )

    for (
        author_id,
        state,
        total_stake,
        possible_payout,
        settled_at,
        updated_at,
        published_at,
        created_at,
    ) in rows:
        result_at = _local(settled_at or updated_at or published_at or created_at)
        if result_at is None:
            continue

        month = date(result_at.year, result_at.month, 1)
        bucket = groups[(author_id, month)]
        stake = total_stake or Decimal("0")
        payout = possible_payout or Decimal("0")
        coefficient = payout / stake if stake > 0 and payout > 0 else Decimal("0")

        bucket["bets"] += 1
        bucket["stake"] += stake
        if coefficient > 0:
            bucket["coefficient_sum"] += coefficient
            bucket["coefficient_count"] += 1

        if state == "win":
            bucket["wins"] += 1
            bucket["profit"] += payout - stake
            if coefficient > 0:
                bucket["flat_units"] += coefficient - Decimal("1")
        elif state == "lose":
            bucket["losses"] += 1
            bucket["profit"] -= stake
            bucket["flat_units"] -= Decimal("1")
        else:
            bucket["refunds"] += 1

    objects = []
    for (author_id, month), bucket in groups.items():
        bets = bucket["bets"]
        avg_coefficient = (
            bucket["coefficient_sum"] / Decimal(bucket["coefficient_count"])
            if bucket["coefficient_count"]
            else Decimal("0")
        )
        objects.append(
            MonthlyStat(
                analyst_id=author_id,
                month=month,
                bets_count=bets,
                wins_count=bucket["wins"],
                losses_count=bucket["losses"],
                refunds_count=bucket["refunds"],
                total_stake=bucket["stake"].quantize(MONEY_STEP, rounding=ROUND_HALF_UP),
                total_profit=bucket["profit"].quantize(MONEY_STEP, rounding=ROUND_HALF_UP),
                flat_profit_percent=_percent(bucket["flat_units"], Decimal(bets)),
                roi=_percent(bucket["profit"], bucket["stake"]),
                avg_coefficient=avg_coefficient.quantize(PERCENT_STEP, rounding=ROUND_HALF_UP),
                hit_rate=_percent(Decimal(bucket["wins"]), Decimal(bets)),
            )
        )

    if objects:
        MonthlyStat.objects.bulk_create(objects, batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0014_sync_account_and_capper_avatars"),
    ]

    operations = [
        migrations.CreateModel(
            name="CapperMonthlyStat",
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
                ("month", models.DateField(db_index=True, verbose_name="Месяц")),
                ("bets_count", models.PositiveIntegerField(default=0, verbose_name="Прогнозов")),
                ("wins_count", models.PositiveIntegerField(default=0, verbose_name="Выигрышей")),
                ("losses_count", models.PositiveIntegerField(default=0, verbose_name="Проигрышей")),
                ("refunds_count", models.PositiveIntegerField(default=0, verbose_name="Возвратов")),
                ("total_stake", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Оборот")),
                ("total_profit", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Прибыль")),
                ("flat_profit_percent", models.DecimalField(decimal_places=2, default=0, max_digits=9, verbose_name="Прибыль флэтом, %")),
                ("roi", models.DecimalField(decimal_places=2, default=0, max_digits=9, verbose_name="ROI, %")),
                ("avg_coefficient", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Средний коэффициент")),
                ("hit_rate", models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name="Проходимость, %")),
                ("calculated_at", models.DateTimeField(auto_now=True, verbose_name="Пересчитано")),
                (
                    "analyst",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monthly_capper_stats",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Каппер",
                    ),
                ),
            ],
            options={
                "verbose_name": "Статистика каппера за месяц",
                "verbose_name_plural": "Статистика капперов по месяцам",
                "ordering": ("-month", "-id"),
                "indexes": [
                    models.Index(fields=["analyst", "month"], name="capmonth_analyst_month_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("analyst", "month"),
                        name="unique_capper_monthly_stat",
                    )
                ],
            },
        ),
        migrations.RunPython(backfill_monthly_stats, migrations.RunPython.noop),
    ]
