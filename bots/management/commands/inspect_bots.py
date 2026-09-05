from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from bots.models import BotAccount, BotExpertStrategy, BotOnlineSession, BotPlannedAction
from bots.services import _is_zero_handicap_selection, _total_line_reasonable, get_bot_runtime_status
from cabinet.presence import UserPresence
from game.models import Prediction, PredictionCoupon
from tournaments.models import Tournament, TournamentParticipant


class Command(BaseCommand):
    help = "Показывает состояние и качество активности ботов."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)
        parser.add_argument("--bad-max-coefficient", type=Decimal, default=Decimal("5.00"))
        parser.add_argument("--issues-limit", type=int, default=5)

    def handle(self, *args, **options):
        now = timezone.now()
        since = now - timedelta(hours=options["hours"])
        bad_max = options["bad_max_coefficient"]

        bots = BotAccount.objects.filter(is_active=True)
        expert_bots = bots.filter(kind=BotAccount.Kind.EXPERT)
        reader_bots = bots.filter(kind=BotAccount.Kind.READER)
        due_strategies = BotExpertStrategy.objects.filter(
            bot__is_active=True,
            bot__kind=BotAccount.Kind.EXPERT,
        ).filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))

        recent_predictions = list(
            Prediction.objects.select_related("coupon", "match")
            .filter(
                coupon__author__bot_account__kind=BotAccount.Kind.EXPERT,
                coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                created_at__gte=since,
            )
            .order_by("-created_at")
        )
        recent_coupons = list(
            PredictionCoupon.objects.filter(
                author__bot_account__kind=BotAccount.Kind.EXPERT,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                created_at__gte=since,
            )
        )

        bad_predictions = [
            prediction
            for prediction in recent_predictions
            if _bad_prediction(prediction, bad_max)
        ]
        markets = Counter(prediction.market for prediction in recent_predictions)
        coupon_types = Counter(coupon.coupon_type for coupon in recent_coupons)
        position_coefficient_buckets = _coefficient_buckets(
            prediction.coefficient for prediction in recent_predictions
        )
        coupon_coefficient_buckets = _coefficient_buckets(
            _coupon_coefficient(coupon) for coupon in recent_coupons
        )
        online_cutoff = now - timedelta(minutes=5)

        live_tournaments = Tournament.objects.filter(
            status=Tournament.Status.PUBLISHED,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        bot_participants = TournamentParticipant.objects.filter(
            user__bot_account__is_active=True,
            status=TournamentParticipant.Status.ACTIVE,
        )
        active_sessions = BotOnlineSession.objects.filter(
            bot__is_active=True,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        recent_sessions = BotOnlineSession.objects.filter(
            bot__is_active=True,
            starts_at__gte=since,
        )
        session_targets = Counter(recent_sessions.values_list("target_actions", flat=True))
        planned_statuses = Counter(
            BotPlannedAction.objects.values_list("status", flat=True)
        )
        planned_due = BotPlannedAction.objects.filter(
            status=BotPlannedAction.Status.PENDING,
            scheduled_at__lte=now,
        ).count()
        runtime_status = get_bot_runtime_status()
        queue_issues = list(
            BotPlannedAction.objects.select_related("bot", "bot__user")
            .filter(
                status__in=[
                    BotPlannedAction.Status.SKIPPED,
                    BotPlannedAction.Status.FAILED,
                ],
            )
            .order_by("-finished_at", "-updated_at", "-id")[: options["issues_limit"]]
        )

        self.stdout.write(f"Период: последние {options['hours']} ч")
        self.stdout.write(f"Runtime: {runtime_status}")
        self.stdout.write(f"Боты: {bots.count()} активных, эксперты {expert_bots.count()}, читатели {reader_bots.count()}")
        self.stdout.write(f"Due стратегий: {due_strategies.count()}")
        self.stdout.write(
            "Онлайн: "
            f"{UserPresence.objects.filter(user__bot_account__is_active=True, last_seen_at__gte=online_cutoff).count()}"
        )
        self.stdout.write(
            f"Купоны: {len(recent_coupons)} за период, типы {dict(coupon_types)}"
        )
        self.stdout.write(
            f"Позиции: {len(recent_predictions)} за период, рынки {dict(markets)}"
        )
        self.stdout.write(
            f"КФ позиций: {dict(position_coefficient_buckets)}"
        )
        self.stdout.write(
            f"КФ купонов: {dict(coupon_coefficient_buckets)}"
        )
        self.stdout.write(
            f"Очередь: due {planned_due}, статусы {dict(planned_statuses)}"
        )
        if queue_issues:
            self.stdout.write("Последние проблемы очереди:")
            for issue in queue_issues:
                self.stdout.write(f"  {_queue_issue_line(issue)}")
        else:
            self.stdout.write("Последние проблемы очереди: нет")
        self.stdout.write(
            "Сессии: "
            f"активные {active_sessions.count()}, за период {recent_sessions.count()}, "
            f"цели действий {dict(session_targets)}"
        )
        self.stdout.write(
            f"Плохие опубликованные позиции за период: {len(bad_predictions)} "
            f"(лимит КФ {bad_max})"
        )
        self.stdout.write(
            f"Live-турниры: {live_tournaments.count()}, активных bot-участий: {bot_participants.count()}"
        )


def _bad_prediction(prediction: Prediction, max_coefficient: Decimal) -> bool:
    if prediction.coefficient > max_coefficient:
        return True
    if prediction.market == "handicap" and _is_zero_handicap_selection(prediction.selection):
        return True
    if prediction.market == "total" and not _total_line_reasonable(prediction.match, prediction.selection):
        return True
    return False


def _coefficient_buckets(values) -> Counter:
    buckets = Counter(
        {
            "1.00-1.49": 0,
            "1.50-1.99": 0,
            "2.00-2.99": 0,
            "3.00-4.50": 0,
            "4.51-8.00": 0,
            ">8.00": 0,
        }
    )
    for value in values:
        if value is None:
            continue
        coefficient = Decimal(str(value))
        if coefficient < Decimal("1.50"):
            buckets["1.00-1.49"] += 1
        elif coefficient < Decimal("2.00"):
            buckets["1.50-1.99"] += 1
        elif coefficient < Decimal("3.00"):
            buckets["2.00-2.99"] += 1
        elif coefficient <= Decimal("4.50"):
            buckets["3.00-4.50"] += 1
        elif coefficient <= Decimal("8.00"):
            buckets["4.51-8.00"] += 1
        else:
            buckets[">8.00"] += 1
    return buckets


def _coupon_coefficient(coupon: PredictionCoupon) -> Decimal | None:
    if not coupon.total_stake:
        return None
    return (coupon.possible_payout / coupon.total_stake).quantize(Decimal("0.01"))


def _queue_issue_line(issue: BotPlannedAction) -> str:
    bot = issue.bot.user.username if issue.bot_id and issue.bot else "system"
    reason = issue.error or _short_json(issue.result) or "без причины"
    finished_at = issue.finished_at or issue.updated_at
    finished_label = timezone.localtime(finished_at).strftime("%d.%m %H:%M") if finished_at else "без даты"
    return (
        f"#{issue.id} {finished_label} {bot} "
        f"{issue.action}/{issue.status}: {reason[:160]}"
    )


def _short_json(value) -> str:
    if not value:
        return ""
    text = str(value)
    return text if len(text) <= 160 else f"{text[:157]}..."
