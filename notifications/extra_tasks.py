import logging
from collections import defaultdict
from datetime import timedelta

from celery import shared_task
from celery.signals import task_postrun
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystProfile, MatchPredictionRequest
from game.models import PredictionCoupon
from tournaments.models import Tournament, TournamentParticipant

from .models import MatchWatch, Notification
from .services import create_notification


logger = logging.getLogger(__name__)
CORE_DISPATCH_TASK_NAME = "notifications.tasks.dispatch_recent_coupon_events"
SETTLED_STATES = {
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
}


def _display_name(user) -> str:
    try:
        profile = user.analyst_profile
    except (AnalystProfile.DoesNotExist, AttributeError):
        profile = None
    if profile and profile.display_name:
        return profile.display_name
    return user.get_full_name().strip() or user.username


def _match_name(match) -> str:
    return f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"


def _prediction_interest_events(now) -> int:
    cutoff = now - timedelta(hours=2)
    coupons = (
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
            published_at__gte=cutoff,
        )
        .select_related("author", "author__analyst_profile")
        .prefetch_related(
            "predictions__match__home_team",
            "predictions__match__away_team",
        )
        .order_by("published_at", "id")
    )

    created = 0
    for coupon in coupons:
        positions = list(coupon.predictions.all())
        match_ids = {position.match_id for position in positions}
        if not match_ids:
            continue

        requests_by_match = defaultdict(list)
        for request in MatchPredictionRequest.objects.filter(
            match_id__in=match_ids
        ).select_related("user"):
            requests_by_match[request.match_id].append(request)

        watches_by_match = defaultdict(list)
        for watch in MatchWatch.objects.filter(match_id__in=match_ids).select_related("user"):
            watches_by_match[watch.match_id].append(watch)

        author_name = _display_name(coupon.author)
        url = reverse("front:prediction_detail", kwargs={"prediction_id": coupon.id})
        for position in positions:
            match = position.match
            match_title = _match_name(match)

            for request in requests_by_match[position.match_id]:
                if request.user_id == coupon.author_id:
                    continue
                notification = create_notification(
                    recipient=request.user,
                    actor=coupon.author,
                    kind=Notification.Kind.REQUESTED_MATCH_PREDICTION,
                    title="Появился прогноз по вашему запросу",
                    message=f"{author_name} опубликовал прогноз на {match_title}.",
                    url=url,
                    event_key=f"requested-match-prediction:{request.user_id}:{coupon.id}:{position.match_id}",
                    meta={
                        "coupon_id": coupon.id,
                        "match_id": position.match_id,
                        "author_id": coupon.author_id,
                        "request_id": request.id,
                    },
                )
                created += int(notification is not None)

            for watch in watches_by_match[position.match_id]:
                if watch.user_id == coupon.author_id:
                    continue
                notification = create_notification(
                    recipient=watch.user,
                    actor=coupon.author,
                    kind=Notification.Kind.MATCH_PREDICTION,
                    title="На отслеживаемый матч появился прогноз",
                    message=f"{author_name} опубликовал прогноз на {match_title}.",
                    url=url,
                    event_key=f"match-prediction:{watch.user_id}:{coupon.id}:{position.match_id}",
                    meta={
                        "coupon_id": coupon.id,
                        "match_id": position.match_id,
                        "author_id": coupon.author_id,
                    },
                )
                created += int(notification is not None)
    return created


def _own_coupon_settlement_events(now) -> int:
    cutoff = now - timedelta(hours=2)
    result_labels = {
        PredictionCoupon.StateStatus.WIN: "выигрыш",
        PredictionCoupon.StateStatus.LOSE: "проигрыш",
        PredictionCoupon.StateStatus.REFUND: "возврат",
    }
    coupons = (
        PredictionCoupon.objects.filter(
            state_status__in=SETTLED_STATES,
            settled_at__gte=cutoff,
        )
        .select_related("author")
        .order_by("settled_at", "id")
    )

    created = 0
    for coupon in coupons:
        result_label = result_labels[coupon.state_status]
        notification = create_notification(
            recipient=coupon.author,
            kind=Notification.Kind.OWN_COUPON_SETTLED,
            title=f"Ваш купон #{coupon.id} рассчитан",
            message=f"Результат купона: {result_label}.",
            url=reverse("front:prediction_detail", kwargs={"prediction_id": coupon.id}),
            event_key=f"own-coupon-settled:{coupon.author_id}:{coupon.id}:{coupon.state_status}",
            meta={"coupon_id": coupon.id, "state": coupon.state_status},
        )
        created += int(notification is not None)
    return created


def _tournament_events(now) -> int:
    created = 0

    started_participants = (
        TournamentParticipant.objects.filter(
            status=TournamentParticipant.Status.ACTIVE,
            tournament__status=Tournament.Status.PUBLISHED,
            tournament__starts_at__lte=now,
            tournament__ends_at__gte=now,
        )
        .select_related("user", "tournament")
        .order_by("id")
    )
    for participant in started_participants:
        tournament = participant.tournament
        notification = create_notification(
            recipient=participant.user,
            kind=Notification.Kind.TOURNAMENT_STARTED,
            title=f"Турнир «{tournament.title}» начался",
            message="Вы участвуете в турнире. Турнирные прогнозы уже учитываются в таблице.",
            url=tournament.get_absolute_url(),
            event_key=f"tournament-started:{participant.id}",
            meta={"tournament_id": tournament.id, "participant_id": participant.id},
        )
        created += int(notification is not None)

    finished_cutoff = now - timedelta(hours=24)
    finished_participants = (
        TournamentParticipant.objects.filter(
            status__in=(
                TournamentParticipant.Status.ACTIVE,
                TournamentParticipant.Status.DISQUALIFIED,
            ),
            tournament__status__in=(Tournament.Status.PUBLISHED, Tournament.Status.ARCHIVED),
            tournament__ends_at__gte=finished_cutoff,
            tournament__ends_at__lt=now,
        )
        .select_related("user", "tournament")
        .order_by("id")
    )
    for participant in finished_participants:
        tournament = participant.tournament
        notification = create_notification(
            recipient=participant.user,
            kind=Notification.Kind.TOURNAMENT_FINISHED,
            title=f"Турнир «{tournament.title}» завершён",
            message="Итоги турнира доступны на странице турнира.",
            url=tournament.get_absolute_url(),
            event_key=f"tournament-finished:{participant.id}",
            meta={"tournament_id": tournament.id, "participant_id": participant.id},
        )
        created += int(notification is not None)

    return created


@shared_task(name="notifications.extra_tasks.dispatch_extended_notification_events")
def dispatch_extended_notification_events() -> dict:
    now = timezone.now()
    return {
        "prediction_interest_events": _prediction_interest_events(now),
        "own_coupon_settlement_events": _own_coupon_settlement_events(now),
        "tournament_events": _tournament_events(now),
    }


@task_postrun.connect
def dispatch_extended_after_core_task(sender=None, **kwargs) -> None:
    if getattr(sender, "name", "") != CORE_DISPATCH_TASK_NAME:
        return
    try:
        dispatch_extended_notification_events.run()
    except Exception:
        logger.exception("Failed to dispatch extended notification events.")
