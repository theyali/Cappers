from django import template
from django.db.models import Sum
from django.utils import timezone

from cabinet.models import AnalystProfile, CapperMonthlyStat, User


register = template.Library()


def _format_count(value) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


@register.simple_tag
def capper_table_hero_stats() -> dict:
    active_profiles = AnalystProfile.objects.filter(
        is_public=True,
        user__role=User.Role.ANALYST,
        user__is_active=True,
    )
    active_ids = active_profiles.values_list("user_id", flat=True)
    stats = CapperMonthlyStat.objects.filter(analyst_id__in=active_ids)
    current_month = timezone.localdate().replace(day=1)

    predictions_month = (
        stats.filter(month=current_month).aggregate(total=Sum("bets_count"))["total"] or 0
    )
    predictions_all_time = stats.aggregate(total=Sum("bets_count"))["total"] or 0

    return {
        "active_cappers": _format_count(active_profiles.count()),
        "predictions_month": _format_count(predictions_month),
        "predictions_all_time": _format_count(predictions_all_time),
    }
