"""Leader award lifecycle. Only background jobs/admin/commands write this registry."""

from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystProfile, CapperMonthlyStat, User
from cabinet.monthly_stats import SETTLED_STATES, rebuild_capper_month
from game.models import PredictionCoupon
from .models import (
    ExpertAllTimeBadgeTenure,
    ExpertMonthlyAward,
    ExpertMonthlyAwardPeriod,
    ExpertRankingSnapshot,
)


RULES_VERSION = "ranking-v1"
MONTH_NAMES = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)


def project_today():
    return timezone.localtime(timezone.now(), timezone.get_default_timezone()).date()


def next_month(month):
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def month_closes_at(month):
    return timezone.make_aware(
        datetime.combine(next_month(month), time(3)), timezone.get_default_timezone()
    )


def track_current_award_month():
    """Start observing now, never implicitly backfill pre-installation history."""
    return ExpertMonthlyAwardPeriod.objects.get_or_create(
        month=project_today().replace(day=1),
        defaults={"observed_automatically": True},
    )[0]


def _ranking_proof(entry):
    from .expert_ranking import _json_restore

    metrics = _json_restore(entry.metrics)
    # Do not retain a FK to an entry: rebuilding a snapshot deletes its rows.
    return {
        "metrics": entry.metrics,
        "roi": str(metrics.get("roi", entry.author_roi)),
        "settled_count": int(metrics.get("bets", entry.settled_count)),
        "ranking_score": str(entry.ranking_score),
        "trust_index": str(entry.trust_index),
        "ranking_reason": entry.ranking_reason,
    }


def _rebuild_month_stats(month):
    start = timezone.make_aware(
        datetime.combine(month, time.min), timezone.get_default_timezone()
    )
    end = timezone.make_aware(
        datetime.combine(next_month(month), time.min), timezone.get_default_timezone()
    )
    result_authors = (
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=SETTLED_STATES,
        )
        .annotate(
            result_at=Coalesce("settled_at", "updated_at", "published_at", "created_at")
        )
        .filter(
            result_at__gte=start,
            result_at__lt=end,
        )
        .values_list("author_id", flat=True)
    )
    stored_authors = CapperMonthlyStat.objects.filter(month=month).values_list(
        "analyst_id", flat=True
    )
    authors = (
        AnalystProfile.objects.filter(is_public=True, user__role=User.Role.ANALYST)
        .filter(Q(user_id__in=result_authors) | Q(user_id__in=stored_authors))
        .values_list("user_id", flat=True)
    )
    for analyst_id in list(authors):
        rebuild_capper_month(analyst_id, month)


@transaction.atomic
def finalize_monthly_awards(
    month, *, correction_reason="", actor=None, source="auto", expected_revision=None
):
    """Idempotent close; corrections preserve revoked proof and require an actor/reason."""
    from .expert_ranking import rebuild_expert_ranking_snapshot

    correction_reason = correction_reason.strip()
    if month.day != 1 or month_closes_at(month) > timezone.now():
        raise ValidationError(
            "Месяц можно закрыть только после 03:00 первого числа следующего месяца."
        )
    if source not in {"auto", "admin", "backfill"}:
        raise ValidationError("Неизвестный источник выдачи.")
    period, _ = ExpertMonthlyAwardPeriod.objects.select_for_update().get_or_create(
        month=month
    )
    if expected_revision is not None and period.revision != expected_revision:
        raise ValidationError(
            "Награды уже изменены. Обновите страницу и проверьте новую редакцию перед исправлением."
        )
    if period.finalized_at and not correction_reason:
        return period
    if correction_reason and (
        not actor
        or not actor.is_staff
        or not actor.has_perm("front.change_expertmonthlyawardperiod")
    ):
        raise ValidationError(
            "Исправление доступно только администратору с правом изменения месяца наград."
        )
    if source == "admin" and not correction_reason.strip():
        raise ValidationError("Укажите причину исправления.")

    _rebuild_month_stats(month)
    snapshot = rebuild_expert_ranking_snapshot(period=month.strftime("%Y-%m"))
    entries = list(snapshot.entries.order_by("rank")[:3])
    now = timezone.now()
    if period.finalized_at:
        period.awards.filter(revoked_at__isnull=True).update(
            revoked_at=now, revocation_reason=correction_reason.strip()
        )
    period.revision += 1
    ExpertMonthlyAward.objects.bulk_create(
        [
            ExpertMonthlyAward(
                period=period,
                analyst_id=entry.analyst_id,
                rank=entry.rank,
                revision=period.revision,
                metrics=_ranking_proof(entry),
                source="admin" if correction_reason else source,
                awarded_at=now,
                reason=correction_reason.strip(),
                actor=actor,
            )
            for entry in entries
        ]
    )
    period.finalized_at = now
    period.ranking_built_at = snapshot.built_at
    period.eligible_count = snapshot.entries_count
    period.rules_version = RULES_VERSION
    period.history = [
        *period.history,
        {
            "revision": period.revision,
            "at": now.isoformat(),
            "snapshot_built_at": snapshot.built_at.isoformat(),
            "source": "admin" if correction_reason else source,
            "actor_id": actor.pk if actor else None,
            "reason": correction_reason.strip(),
            "eligible_count": snapshot.entries_count,
            "winners": [
                {"analyst_id": entry.analyst_id, "rank": entry.rank}
                for entry in entries
            ],
            "empty_reason": "Нет участников общего рейтинга за месяц"
            if not entries
            else "",
        },
    ]
    period.save()
    from .expert_ranking import invalidate_expert_ranking_cache

    transaction.on_commit(invalidate_expert_ranking_cache)
    return period


def close_due_award_months():
    current = track_current_award_month()
    month = (
        ExpertMonthlyAwardPeriod.objects.filter(observed_automatically=True)
        .order_by("month")
        .values_list("month", flat=True)
        .first()
    )
    finalized = set(
        ExpertMonthlyAwardPeriod.objects.filter(finalized_at__isnull=False).values_list(
            "month", flat=True
        )
    )
    closed = []
    # An explicit historical backfill must not expand the automatic catch-up range.
    while month < current.month and month_closes_at(month) <= timezone.now():
        if month not in finalized:
            period = finalize_monthly_awards(month)
            closed.append(str(period))
        month = next_month(month)
    return closed


def _tier(rank):
    return 1 if rank == 1 else 3 if rank <= 3 else 10


@transaction.atomic
def sync_all_time_badges(snapshot_id, *, expected_built_at=None):
    """Serialize on the canonical snapshot; delayed jobs cannot publish an old generation."""
    snapshot = ExpertRankingSnapshot.objects.select_for_update().get(pk=snapshot_id)
    if (
        snapshot.period,
        snapshot.sport_code,
        snapshot.group,
        snapshot.roi_period_days,
    ) != ("all-time", "all", "all", None):
        raise ValidationError("Знаки выдаются только по общему рейтингу за всё время.")
    if expected_built_at is not None and snapshot.built_at != expected_built_at:
        return False
    track_current_award_month()
    entries = {
        entry.analyst_id: entry for entry in snapshot.entries.order_by("rank")[:10]
    }
    active = list(
        ExpertAllTimeBadgeTenure.objects.select_for_update().filter(
            ended_at__isnull=True
        )
    )
    # Reprocessing the exact generation must not change timestamps/history.
    if (
        active
        and max(tenure.ranking_built_at for tenure in active) >= snapshot.built_at
    ):
        return False
    now = timezone.now()
    unchanged = set()
    to_end = []
    for tenure in active:
        entry = entries.get(tenure.analyst_id)
        if entry is None or tenure.tier != _tier(entry.rank):
            to_end.append(tenure.pk)
        else:
            tenure.current_rank = entry.rank
            tenure.ranking_built_at = snapshot.built_at
            unchanged.add(tenure.analyst_id)
    # End all old slots before inserting a new #1 (partial unique constraint).
    ExpertAllTimeBadgeTenure.objects.filter(pk__in=to_end).update(ended_at=now)
    ExpertAllTimeBadgeTenure.objects.bulk_update(
        [tenure for tenure in active if tenure.analyst_id in unchanged],
        ("current_rank", "ranking_built_at"),
    )
    ExpertAllTimeBadgeTenure.objects.bulk_create(
        [
            ExpertAllTimeBadgeTenure(
                analyst_id=entry.analyst_id,
                tier=_tier(entry.rank),
                entry_rank=entry.rank,
                current_rank=entry.rank,
                metrics=_ranking_proof(entry),
                started_at=now,
                ranking_built_at=snapshot.built_at,
                rules_version=RULES_VERSION,
            )
            for entry in entries.values()
            if entry.analyst_id not in unchanged
        ]
    )
    from .expert_ranking import invalidate_expert_ranking_cache

    transaction.on_commit(invalidate_expert_ranking_cache)
    return True


def check_expert_awards():
    """Read registry facts without rebuilding rankings, awarding or repairing data."""
    from django_celery_beat.models import PeriodicTask
    from .expert_ranking import rank_experts

    errors, warnings = [], []
    with transaction.atomic():
        # The producer locks this same row. Keep both reads on one generation.
        snapshot = (
            ExpertRankingSnapshot.objects.select_for_update()
            .filter(
                period="all-time",
                sport_code="all",
                group="all",
                roi_period_days=None,
            )
            .first()
        )
        active = list(ExpertAllTimeBadgeTenure.objects.filter(ended_at__isnull=True))
        if snapshot is None:
            errors.append(
                "Нет канонического all-time снимка; требуется первичная синхронизация."
            )
        else:
            expected = {
                entry["profile"].user_id: (entry["rank"], _tier(entry["rank"]))
                for entry in rank_experts(
                    period="all-time", sport_code="all", group="all", limit=10
                )
            }
            actual = {row.analyst_id: (row.current_rank, row.tier) for row in active}
            if len(actual) != len(active):
                errors.append("У каппера несколько открытых all-time интервалов.")
            if expected != actual:
                errors.append(
                    "Текущие all-time места или уровни не совпадают с каноническим рейтингом."
                )
            if any(row.ranking_built_at != snapshot.built_at for row in active):
                errors.append(
                    "Поколение all-time реестра отличается от поколения снимка."
                )

    previous = {}
    for row in ExpertAllTimeBadgeTenure.objects.order_by(
        "analyst_id", "started_at", "pk"
    ).iterator(chunk_size=500):
        if row.analyst_id in previous and (
            previous[row.analyst_id] is None
            or row.started_at < previous[row.analyst_id]
        ):
            errors.append(
                f"Пересекающиеся all-time интервалы у каппера {row.analyst_id}."
            )
        previous[row.analyst_id] = row.ended_at
        if row.tier != _tier(row.entry_rank) or row.tier != _tier(row.current_rank):
            errors.append(
                f"Уровень all-time интервала {row.pk} не соответствует сохранённым местам."
            )

    is_active = Q(awards__revoked_at__isnull=True)
    periods = list(
        ExpertMonthlyAwardPeriod.objects.annotate(
            active_count=Count("awards", filter=is_active),
            analyst_count=Count("awards__analyst", filter=is_active, distinct=True),
            rank_count=Count("awards__rank", filter=is_active, distinct=True),
            revision_count=Count(
                "awards", filter=is_active & Q(awards__revision=F("revision"))
            ),
        ).order_by("month")
    )
    observed = [period.month for period in periods if period.observed_automatically]
    if not observed:
        errors.append("Не зафиксирован месяц начала наблюдения.")
    due_month = min(observed) if observed else None
    closed_months = {period.month for period in periods if period.finalized_at}
    while due_month and month_closes_at(due_month) <= timezone.now():
        if due_month not in closed_months:
            errors.append(
                f"Не закрыт наблюдаемый месяц {due_month:%Y-%m}; проверьте worker и Beat."
            )
        due_month = next_month(due_month)
    for period in periods:
        if (
            period.active_count != period.analyst_count
            or period.active_count != period.rank_count
        ):
            errors.append(f"Дубли активных месячных наград за {period}.")
        if not period.finalized_at:
            if period.active_count or period.revision or period.history:
                errors.append(
                    f"В незакрытом месяце {period} есть награды или история выдачи."
                )
            continue
        if period.finalized_at < month_closes_at(period.month):
            errors.append(f"Месяц {period} закрыт раньше разрешённого времени.")
        if not period.ranking_built_at or not period.revision or not period.history:
            errors.append(
                f"У закрытого месяца {period} не хватает доказательных данных."
            )
        if period.active_count != period.revision_count:
            errors.append(f"Активные награды за {period} принадлежат разным редакциям.")
        if period.active_count != min(3, period.eligible_count):
            warnings.append(
                f"За {period} состав наград неполный; проверьте журнал исправлений и удаления аккаунтов."
            )

    schedules = list(
        PeriodicTask.objects.filter(
            task="front.tasks.close_expert_award_months_task",
            enabled=True,
        ).select_related("crontab")
    )
    if len(schedules) != 1:
        errors.append(
            f"Нужно одно включённое расписание закрытия месяца, найдено: {len(schedules)}."
        )
    else:
        cron = schedules[0].crontab
        if cron is None or (
            cron.minute,
            cron.hour,
            cron.day_of_week,
            cron.day_of_month,
            cron.month_of_year,
        ) != ("0", "3", "*", "*", "*"):
            errors.append(
                "Расписание закрытия месяца должно запускаться ежедневно в 03:00."
            )
        if cron is not None and str(cron.timezone) != settings.TIME_ZONE:
            errors.append(
                "Таймзона расписания закрытия месяца отличается от TIME_ZONE."
            )
    if settings.CELERY_TIMEZONE != settings.TIME_ZONE:
        errors.append("Таймзона Celery отличается от TIME_ZONE проекта.")
    return {
        "errors": errors,
        "warnings": warnings,
        "active_all_time": len(active),
        "monthly_periods": len(periods),
        "monthly_awards": ExpertMonthlyAward.objects.filter(
            revoked_at__isnull=True
        ).count(),
    }


def _monthly_badge(award, shown_month):
    label = f"{award.rank} место · {MONTH_NAMES[award.period.month.month - 1]} {award.period.month.year}"
    return {
        "kind": "month",
        "rank": award.rank,
        "month": award.period.month,
        "title": "Лучший каппер месяца"
        if award.rank == 1
        else f"{award.rank}-е место месяца",
        "label": label,
        "period_label": f"{MONTH_NAMES[award.period.month.month - 1]} {award.period.month.year}",
        "status": "active" if award.period.month == shown_month else "historical",
        "metrics": award.metrics,
        "awarded_at": award.awarded_at,
        "detail_url": reverse("front:expert_profile", args=(award.analyst.username,))
        + f"#leader-month-{award.pk}",
        "anchor": f"leader-month-{award.pk}",
    }


def _all_time_badge(tenure):
    title = (
        "Легенда · №1 за всё время"
        if tenure.tier == 1
        else f"Топ-{tenure.tier} за всё время"
    )
    project_tz = timezone.get_default_timezone()
    shelf_caption = "Действует"
    if tenure.ended_at:
        started = timezone.localtime(tenure.started_at, project_tz).strftime("%d.%m.%Y")
        ended = timezone.localtime(tenure.ended_at, project_tz).strftime("%d.%m.%Y")
        shelf_caption = f"{started} — {ended}"
    return {
        "kind": "all-time",
        "rank": tenure.current_rank,
        "title": title,
        "label": title
        + (" · исторический знак" if tenure.ended_at else " · текущий знак"),
        "status": "historical" if tenure.ended_at else "active",
        "shelf_caption": shelf_caption,
        "started_at": tenure.started_at,
        "ended_at": tenure.ended_at,
        "metrics": tenure.metrics,
        "detail_url": reverse("front:expert_profile", args=(tenure.analyst.username,))
        + f"#leader-all-time-{tenure.pk}",
        "anchor": f"leader-all-time-{tenure.pk}",
    }


def leader_badges_for_users(user_ids):
    """Batch projection for all surfaces; no awards are created while reading."""
    ids = set(user_ids)
    result = {user_id: [] for user_id in ids}
    if not ids:
        return result
    public_ids = AnalystProfile.objects.filter(
        user_id__in=ids, is_public=True, user__role=User.Role.ANALYST
    ).values_list("user_id", flat=True)
    today = project_today()
    shown_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    monthly = (
        ExpertMonthlyAward.objects.filter(
            analyst_id__in=public_ids,
            revoked_at__isnull=True,
            period__finalized_at__isnull=False,
        )
        .select_related("period", "analyst")
        .order_by("-period__month", "rank")
    )
    all_time = ExpertAllTimeBadgeTenure.objects.filter(
        analyst_id__in=public_ids
    ).select_related("analyst")
    monthly = monthly.filter(period__month=shown_month)
    all_time = all_time.filter(ended_at__isnull=True)
    for award in monthly:
        result[award.analyst_id].append(_monthly_badge(award, shown_month))
    for tenure in all_time.order_by("-started_at", "pk"):
        result[tenure.analyst_id].append(_all_time_badge(tenure))
    return result


def build_leader_profile_context(user_id, params):
    """Monthly history and the current all-time level; never former all-time titles."""
    badges = leader_badges_for_users([user_id]).get(user_id, [])
    public_ids = AnalystProfile.objects.filter(
        user_id=user_id, is_public=True, user__role=User.Role.ANALYST
    ).values_list("user_id", flat=True)
    monthly = (
        ExpertMonthlyAward.objects.filter(
            analyst_id__in=public_ids,
            revoked_at__isnull=True,
            period__finalized_at__isnull=False,
        )
        .select_related("period", "analyst")
        .order_by("-period__month", "pk")
    )
    all_time = (
        ExpertAllTimeBadgeTenure.objects.filter(
            analyst_id__in=public_ids, ended_at__isnull=True
        )
        .select_related("analyst")
        .order_by("-started_at", "-pk")
    )
    monthly_page = Paginator(monthly, 12).get_page(params.get("leader_month_page"))
    all_time_page = Paginator(all_time, 12).get_page(params.get("leader_all_time_page"))
    total = monthly_page.paginator.count + all_time_page.paginator.count
    shown_month = (project_today().replace(day=1) - timedelta(days=1)).replace(day=1)
    groups = []
    for kind, title, page, key, payload in (
        (
            "all-time",
            "За всё время",
            all_time_page,
            "leader_all_time_page",
            _all_time_badge,
        ),
        (
            "month",
            "Месяцы",
            monthly_page,
            "leader_month_page",
            lambda row: _monthly_badge(row, shown_month),
        ),
    ):

        def page_url(number):
            query = params.copy()
            query[key] = str(number)
            return f"?{query.urlencode()}#achievements"

        groups.append(
            {
                "kind": kind,
                "title": title,
                "empty_label": "Сейчас каппер не входит в топ-10 за всё время."
                if kind == "all-time"
                else "Месячных медалей пока нет.",
                "count": page.paginator.count,
                "badges": [payload(row) for row in page.object_list],
                "previous_url": page_url(page.previous_page_number())
                if page.has_previous()
                else "",
                "next_url": page_url(page.next_page_number())
                if page.has_next()
                else "",
                "page_label": f"{page.number} / {page.paginator.num_pages}",
            }
        )
    return {
        "leader_badges": badges,
        "leader_badges_more_count": max(0, total - len(badges)),
        "leader_shelf_groups": groups,
        "leader_awards_count": total,
    }
