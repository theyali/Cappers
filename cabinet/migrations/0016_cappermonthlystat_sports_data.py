from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models
from django.utils import timezone


MONEY_STEP = Decimal("0.01")
VALUE_STEP = Decimal("0.01")
SPORT_FALLBACK_CODE = "football"
SPORT_FALLBACK_NAME = "Футбол"
SPORT_NAMES_RU = {
    "football": "Футбол",
    "hockey": "Хоккей",
    "basketball": "Баскетбол",
    "tennis": "Теннис",
}


def _local(value):
    if value is not None and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def _coupon_coefficient(stake, payout):
    stake = stake or Decimal("0")
    payout = payout or Decimal("0")
    if stake <= 0 or payout <= 0:
        return Decimal("0")
    return payout / stake


def _coupon_profit(state, stake, payout):
    stake = stake or Decimal("0")
    payout = payout or Decimal("0")
    if state == "win":
        return payout - stake
    if state == "lose":
        return -stake
    return Decimal("0")


def _coupon_flat_units(state, coefficient):
    if state == "lose":
        return Decimal("-1")
    if state == "refund":
        return Decimal("0")
    return coefficient - Decimal("1") if coefficient > 0 else Decimal("0")


def backfill_sports_data(apps, schema_editor):
    Coupon = apps.get_model("game", "PredictionCoupon")
    Prediction = apps.get_model("game", "Prediction")
    MonthlyStat = apps.get_model("cabinet", "CapperMonthlyStat")

    coupon_rows = list(
        Coupon.objects.filter(
            published_status="published",
            state_status__in=("win", "lose", "refund"),
        ).values(
            "id",
            "author_id",
            "state_status",
            "total_stake",
            "possible_payout",
            "settled_at",
            "updated_at",
            "published_at",
            "created_at",
        )
    )
    if not coupon_rows:
        return

    sport_counts = defaultdict(Counter)
    sport_names = defaultdict(dict)
    for coupon_id, code, name_ru, name in (
        Prediction.objects.filter(
            coupon__published_status="published",
            coupon__state_status__in=("win", "lose", "refund"),
        )
        .values_list(
            "coupon_id",
            "match__sport__code",
            "match__sport__name_ru",
            "match__sport__name",
        )
        .iterator(chunk_size=4000)
    ):
        sport_code = code or SPORT_FALLBACK_CODE
        sport_name = name_ru or name or SPORT_NAMES_RU.get(sport_code) or sport_code.capitalize()
        sport_counts[coupon_id][sport_code] += 1
        sport_names[coupon_id][sport_code] = sport_name

    grouped = defaultdict(
        lambda: defaultdict(
            lambda: {
                "name": "",
                "predictions_count": 0,
                "wins_count": 0,
                "losses_count": 0,
                "refunds_count": 0,
                "allocated_stake": Decimal("0"),
                "allocated_profit": Decimal("0"),
                "flat_units": Decimal("0"),
                "weight": Decimal("0"),
                "coefficient_sum": Decimal("0"),
            }
        )
    )

    for row in coupon_rows:
        result_at = _local(
            row["settled_at"]
            or row["updated_at"]
            or row["published_at"]
            or row["created_at"]
        )
        if result_at is None:
            continue
        month = date(result_at.year, result_at.month, 1)
        counts = sport_counts.get(row["id"])
        names = sport_names.get(row["id"], {})
        if not counts:
            counts = Counter({SPORT_FALLBACK_CODE: 1})
            names = {SPORT_FALLBACK_CODE: SPORT_FALLBACK_NAME}

        total_items = sum(counts.values()) or 1
        stake = row["total_stake"] or Decimal("0")
        payout = row["possible_payout"] or Decimal("0")
        coefficient = _coupon_coefficient(stake, payout)
        profit = _coupon_profit(row["state_status"], stake, payout)
        flat_units = _coupon_flat_units(row["state_status"], coefficient)

        for code, item_count in counts.items():
            share = Decimal(item_count) / Decimal(total_items)
            bucket = grouped[(row["author_id"], month)][code]
            bucket["name"] = names.get(code) or SPORT_NAMES_RU.get(code) or code.capitalize()
            bucket["predictions_count"] += 1
            if row["state_status"] == "win":
                bucket["wins_count"] += 1
            elif row["state_status"] == "lose":
                bucket["losses_count"] += 1
            else:
                bucket["refunds_count"] += 1
            bucket["allocated_stake"] += stake * share
            bucket["allocated_profit"] += profit * share
            bucket["flat_units"] += flat_units * share
            bucket["weight"] += share
            if coefficient > 0:
                bucket["coefficient_sum"] += coefficient * share

    for (author_id, month), sports in grouped.items():
        payload = {}
        for code, bucket in sports.items():
            payload[code] = {
                "code": code,
                "name": bucket["name"],
                "predictions_count": bucket["predictions_count"],
                "wins_count": bucket["wins_count"],
                "losses_count": bucket["losses_count"],
                "refunds_count": bucket["refunds_count"],
                "allocated_stake": str(
                    bucket["allocated_stake"].quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
                ),
                "allocated_profit": str(
                    bucket["allocated_profit"].quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
                ),
                "flat_units": str(
                    bucket["flat_units"].quantize(VALUE_STEP, rounding=ROUND_HALF_UP)
                ),
                "weight": str(bucket["weight"].quantize(VALUE_STEP, rounding=ROUND_HALF_UP)),
                "coefficient_sum": str(
                    bucket["coefficient_sum"].quantize(VALUE_STEP, rounding=ROUND_HALF_UP)
                ),
            }
        MonthlyStat.objects.filter(analyst_id=author_id, month=month).update(
            sports_data=payload
        )


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0015_cappermonthlystat"),
        ("game", "0017_match_provider_predictions_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="cappermonthlystat",
            name="sports_data",
            field=models.JSONField(
                blank=True,
                default=dict,
                verbose_name="Статистика по видам спорта",
            ),
        ),
        migrations.RunPython(backfill_sports_data, migrations.RunPython.noop),
    ]
