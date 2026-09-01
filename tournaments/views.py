import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import BooleanField, Case, Count, Exists, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from cabinet.models import AnalystFollow
from front.models import PredictionFavorite, PredictionLike
from front.views import _initials
from game import date_views
from game.models import Match, Prediction, PredictionCoupon
from game.services.coupon_validation import CouponMatchVerificationError
from game.views import _latest_predictions, _match_winner_odds
from notifications.models import MatchWatch
from tournaments.models import Tournament, TournamentParticipant, TournamentPredictionEntry
from tournaments.services.coupons import create_tournament_coupon
from tournaments.services.join import TournamentJoinError, get_active_participant, join_tournament
from tournaments.services.leaderboard import tournament_leaderboard
from wallets.services import InsufficientBalance, format_money


def index(request):
    now = timezone.now()
    tournaments = (
        Tournament.objects.filter(status=Tournament.Status.PUBLISHED)
        .prefetch_related("achievements")
        .annotate(
            participants_count=Count(
                "participants",
                filter=Q(participants__status=TournamentParticipant.Status.ACTIVE),
                distinct=True,
            ),
            coupons_count=Count("tournament_coupons", distinct=True),
        )
        .order_by("-is_featured", "-starts_at", "-id")
    )
    cards = [_tournament_card(tournament, now) for tournament in tournaments]
    return render(
        request,
        "tournaments/index.html",
        {
            "tournaments": cards,
            "now": now,
        },
    )


def detail(request, slug: str):
    tournament = get_object_or_404(
        Tournament.objects.prefetch_related("allowed_sports", "achievements"),
        slug=slug,
        status=Tournament.Status.PUBLISHED,
    )
    participant = get_active_participant(request.user, tournament)
    leaderboard = tournament_leaderboard(tournament)
    prediction_cards = _tournament_prediction_cards(request, tournament)

    return render(
        request,
        "tournaments/detail.html",
        {
            "tournament": tournament,
            "runtime_status": _runtime_status(tournament, timezone.now()),
            "participant": participant,
            "participants_count": TournamentParticipant.objects.filter(
                tournament=tournament,
                status=TournamentParticipant.Status.ACTIVE,
            ).count(),
            "leaderboard": leaderboard[:20],
            "prediction_cards": prediction_cards,
            "allowed_sports": list(tournament.allowed_sports.all()),
            "achievements": list(tournament.achievements.all()),
        },
    )


def predict(request, slug: str):
    tournament = get_object_or_404(
        Tournament.objects.prefetch_related("allowed_sports"),
        slug=slug,
        status=Tournament.Status.PUBLISHED,
    )
    participant = get_active_participant(request.user, tournament)
    if participant is None:
        messages.error(request, "Подключитесь к турниру, чтобы сделать прогноз.")
        return redirect(tournament.get_absolute_url())
    if tournament.runtime_status != "live":
        messages.error(request, "Прогнозы доступны только во время турнира.")
        return redirect(tournament.get_absolute_url())

    today = timezone.localdate()
    selected_date = date_views._selected_date(request.GET.get("date"), today=today)
    min_match_date = today - timedelta(days=date_views.MATCH_DATE_INDEX_WINDOW_DAYS)
    max_match_date = today + timedelta(days=date_views.MATCH_DATE_INDEX_WINDOW_DAYS)
    if not date_views._date_in_index_window(selected_date, today=today):
        selected_date = today

    active_scope = request.GET.get("scope") or PredictionMatchScope.PREMATCH
    valid_scopes = {scope for scope, _ in _tournament_scope_filters()}
    if active_scope not in valid_scopes:
        active_scope = PredictionMatchScope.PREMATCH

    allowed_sport_codes = set(tournament.allowed_sports.values_list("code", flat=True))
    active_sport = request.GET.get("sport") or "all"
    valid_sports = {sport for sport, _ in _tournament_sport_filters(allowed_sport_codes)}
    if active_sport not in valid_sports:
        active_sport = "all"

    day_start, day_end = date_views._local_day_bounds(selected_date)
    base_matches = MatchQuery.base(day_start, day_end, active_scope)
    base_matches = _filter_tournament_allowed_sports(base_matches, allowed_sport_codes)
    base_matches = _filter_tournament_sport(base_matches, active_sport)
    if active_scope == PredictionMatchScope.WATCHED:
        base_matches = base_matches.filter(notification_watchers__user=request.user).distinct()
    matches_queryset = MatchQuery.decorate(base_matches, request.user)

    page_obj = _tournament_page(matches_queryset, request.GET.get("page"))
    matches = list(page_obj.object_list)
    total_count = matches_queryset.count()
    _decorate_tournament_matches(matches, tournament, participant)

    scope_tabs = _tournament_scope_tabs(
        request,
        tournament,
        active_scope=active_scope,
        active_sport=active_sport,
        selected_date=selected_date,
        day_start=day_start,
        day_end=day_end,
        allowed_sport_codes=allowed_sport_codes,
    )
    sport_tabs = _tournament_sport_tabs(
        request,
        tournament,
        active_scope=active_scope,
        active_sport=active_sport,
        selected_date=selected_date,
        day_start=day_start,
        day_end=day_end,
        allowed_sport_codes=allowed_sport_codes,
    )
    date_shortcuts = _tournament_date_shortcuts(
        request,
        tournament,
        active_scope=active_scope,
        active_sport=active_sport,
        selected_date=selected_date,
        today=today,
    )

    previous_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)
    previous_date_url = (
        _tournament_predict_url(tournament, scope=active_scope, sport=active_sport, selected_date=previous_date)
        if previous_date >= min_match_date
        else ""
    )
    next_date_url = (
        _tournament_predict_url(tournament, scope=active_scope, sport=active_sport, selected_date=next_date)
        if next_date <= max_match_date
        else ""
    )

    return render(
        request,
        "tournaments/predict.html",
        {
            "tournament": tournament,
            "runtime_status": _runtime_status(tournament, timezone.now()),
            "participant": participant,
            "active_scope": active_scope,
            "active_sport": active_sport,
            "content_view_mode": "grid",
            "scope_tabs": scope_tabs,
            "sport_tabs": sport_tabs,
            "matches": matches,
            "page_obj": page_obj,
            "can_write_coupon": True,
            "latest_predictions": _latest_predictions(),
            "draft_coupon": None,
            "coupon_match_stale_seconds": 60,
            "selected_date": selected_date,
            "selected_date_iso": selected_date.isoformat(),
            "min_match_date_iso": min_match_date.isoformat(),
            "max_match_date_iso": max_match_date.isoformat(),
            "show_date_filter": True,
            "date_picker_url_template": _tournament_predict_url(
                tournament,
                scope=active_scope,
                sport=active_sport,
                selected_date="__DATE__",
            ),
            "previous_date_iso": previous_date.isoformat(),
            "previous_date_url": previous_date_url,
            "next_date_iso": next_date.isoformat(),
            "next_date_url": next_date_url,
            "date_shortcuts": date_shortcuts,
            "today_iso": today.isoformat(),
            "match_list_h1": f"{tournament.title}: прогноз",
            "match_list_hero_meta": "матчей доступно",
            "total_count": total_count,
            "hero_count": total_count,
        },
    )


@require_POST
def join(request, slug: str):
    tournament = get_object_or_404(Tournament, slug=slug, status=Tournament.Status.PUBLISHED)
    try:
        join_tournament(request.user, tournament)
    except TournamentJoinError as exc:
        messages.error(request, _validation_message(exc))
    else:
        messages.success(request, "Вы подключились к турниру.")
    return redirect(tournament.get_absolute_url())


@require_POST
def create_coupon(request, slug: str):
    tournament = get_object_or_404(Tournament, slug=slug)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Некорректный JSON."}, status=400)

    try:
        coupon, tournament_coupon = create_tournament_coupon(
            user=request.user,
            tournament=tournament,
            payload=payload,
        )
    except PermissionDenied as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=403)
    except InsufficientBalance as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=402)
    except CouponMatchVerificationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

    request.user.capper_balance.refresh_from_db()
    return JsonResponse(
        {
            "ok": True,
            "coupon_id": coupon.id,
            "tournament_coupon_id": tournament_coupon.id,
            "tournament_id": tournament.id,
            "message": "Прогноз турнира опубликован.",
            "coupon_url": reverse("front:prediction_detail", kwargs={"prediction_id": coupon.id}),
            "balance": str(request.user.capper_balance.balance),
            "balance_display": format_money(request.user.capper_balance.balance),
        }
    )


def _validation_message(exc: ValidationError) -> str:
    return exc.messages[0] if exc.messages else "Некорректные данные."


class PredictionMatchScope:
    PREMATCH = Match.SyncScope.PREMATCH
    WATCHED = date_views.WATCHED_SCOPE


class MatchQuery:
    @staticmethod
    def base(day_start, day_end, active_scope: str):
        return Match.objects.filter(
            starts_at__gte=day_start,
            starts_at__lt=day_end,
            sync_scope=Match.SyncScope.PREMATCH,
        )

    @staticmethod
    def decorate(queryset, user):
        if user.is_authenticated:
            watch_exists = MatchWatch.objects.filter(
                user=user,
                match_id=OuterRef("pk"),
                match__sync_scope__in=date_views.ACTIVE_WATCH_SCOPES,
            )
            watched_annotation = Exists(watch_exists)
        else:
            watched_annotation = Value(False, output_field=BooleanField())

        return (
            queryset.select_related("sport", "league__country", "home_team", "away_team", "odds")
            .annotate(
                is_watched=watched_annotation,
                scope_order=Case(
                    When(sync_scope=Match.SyncScope.PREMATCH, then=Value(1)),
                    default=Value(3),
                    output_field=IntegerField(),
                ),
                predictions_count=Count(
                    "predictions__coupon",
                    filter=Q(
                        predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                        predictions__coupon__is_paid=False,
                    ),
                    distinct=True,
                ),
            )
            .order_by("-is_watched", "scope_order", "starts_at", "id")
        )


def _tournament_scope_filters():
    return (
        (PredictionMatchScope.PREMATCH, "Предстоящие"),
        (PredictionMatchScope.WATCHED, "Отслеживаемые"),
    )


def _tournament_sport_filters(allowed_sport_codes: set[str]):
    filters = list(date_views.SPORT_FILTERS)
    if not allowed_sport_codes:
        return filters
    return [
        (code, label)
        for code, label in filters
        if code == "all" or code in allowed_sport_codes
    ]


def _filter_tournament_allowed_sports(queryset, allowed_sport_codes: set[str]):
    if not allowed_sport_codes:
        return queryset
    return queryset.filter(sport__code__in=allowed_sport_codes)


def _filter_tournament_sport(queryset, sport_code: str):
    if sport_code == "all":
        return queryset
    return queryset.filter(sport__code=sport_code)


def _tournament_page(matches_queryset, raw_page):
    paginator = Paginator(matches_queryset, date_views.MATCHES_PAGE_SIZE)
    try:
        return paginator.page(raw_page or "1")
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def _decorate_tournament_matches(
    matches: list[Match],
    tournament: Tournament,
    participant: TournamentParticipant,
) -> None:
    used_match_ids = set(
        TournamentPredictionEntry.objects.filter(
            tournament=tournament,
            participant=participant,
            tournament_coupon__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        ).values_list("match_id", flat=True)
    )
    for match in matches:
        match.coupon_odds = _match_winner_odds(match)
        match.tournament_match_used = match.id in used_match_ids


def _tournament_scope_tabs(
    request,
    tournament: Tournament,
    *,
    active_scope: str,
    active_sport: str,
    selected_date,
    day_start,
    day_end,
    allowed_sport_codes: set[str],
) -> list[dict]:
    tabs = []
    for scope, label in _tournament_scope_filters():
        queryset = MatchQuery.base(day_start, day_end, scope)
        queryset = _filter_tournament_allowed_sports(queryset, allowed_sport_codes)
        queryset = _filter_tournament_sport(queryset, active_sport)
        if scope == PredictionMatchScope.WATCHED:
            queryset = queryset.filter(notification_watchers__user=request.user).distinct()
        tabs.append(
            {
                "scope": scope,
                "label": label,
                "count": queryset.count(),
                "url": _tournament_predict_url(
                    tournament,
                    scope=scope,
                    sport=active_sport,
                    selected_date=selected_date,
                ),
            }
        )
    return tabs


def _tournament_sport_tabs(
    request,
    tournament: Tournament,
    *,
    active_scope: str,
    active_sport: str,
    selected_date,
    day_start,
    day_end,
    allowed_sport_codes: set[str],
) -> list[dict]:
    tabs = []
    base_queryset = MatchQuery.base(day_start, day_end, active_scope)
    base_queryset = _filter_tournament_allowed_sports(base_queryset, allowed_sport_codes)
    if active_scope == PredictionMatchScope.WATCHED:
        base_queryset = base_queryset.filter(notification_watchers__user=request.user).distinct()
    for sport, label in _tournament_sport_filters(allowed_sport_codes):
        queryset = base_queryset if sport == "all" else base_queryset.filter(sport__code=sport)
        tabs.append(
            {
                "code": sport,
                "label": label,
                "count": queryset.count(),
                "url": _tournament_predict_url(
                    tournament,
                    scope=active_scope,
                    sport=sport,
                    selected_date=selected_date,
                ),
            }
        )
    return tabs


def _tournament_date_shortcuts(
    request,
    tournament: Tournament,
    *,
    active_scope: str,
    active_sport: str,
    selected_date,
    today,
) -> list[dict]:
    shortcuts = []
    for label, shortcut_date in (
        ("Вчера", today - timedelta(days=1)),
        ("Сегодня", today),
        ("Завтра", today + timedelta(days=1)),
    ):
        shortcuts.append(
            {
                "label": label,
                "date": shortcut_date,
                "iso": shortcut_date.isoformat(),
                "is_active": shortcut_date == selected_date,
                "url": _tournament_predict_url(
                    tournament,
                    scope=active_scope,
                    sport=active_sport,
                    selected_date=shortcut_date,
                ),
            }
        )
    return shortcuts


def _tournament_predict_url(tournament: Tournament, *, scope, sport, selected_date) -> str:
    selected_date_iso = (
        selected_date.isoformat()
        if hasattr(selected_date, "isoformat")
        else str(selected_date)
    )
    return (
        f"{reverse('tournaments:predict', kwargs={'slug': tournament.slug})}"
        f"?scope={scope}&sport={sport}&date={selected_date_iso}"
    )


def _tournament_card(tournament: Tournament, now) -> SimpleNamespace:
    return SimpleNamespace(
        tournament=tournament,
        runtime_status=_runtime_status(tournament, now),
        participants_count=getattr(tournament, "participants_count", 0),
        coupons_count=getattr(tournament, "coupons_count", 0),
    )


def _runtime_status(tournament: Tournament, now) -> dict:
    if now < tournament.starts_at:
        return {
            "key": "upcoming",
            "label": "Не начался",
            "target_at": tournament.starts_at,
            "target_label": "До старта",
        }
    if now > tournament.ends_at:
        return {
            "key": "finished",
            "label": "Завершён",
            "target_at": tournament.ends_at,
            "target_label": "Финиш",
        }
    return {
        "key": "live",
        "label": "Идёт сейчас",
        "target_at": tournament.ends_at,
        "target_label": "До окончания",
    }


def _tournament_prediction_cards(request, tournament: Tournament):
    coupons = (
        PredictionCoupon.objects.filter(
            tournament_link__tournament=tournament,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related("author", "author__analyst_profile")
        .prefetch_related(
            Prefetch(
                "predictions",
                queryset=Prediction.objects.select_related(
                    "match__sport",
                    "match__league__country",
                    "match__home_team",
                    "match__away_team",
                ).order_by("id"),
                to_attr="card_positions",
            )
        )
        .annotate(
            likes_count=Count("likes", distinct=True),
            favorites_count=Count("favorites", distinct=True),
            positions_count=Count("predictions", distinct=True),
        )
        .order_by("-published_at", "-created_at")[:12]
    )

    liked_ids: set[int] = set()
    favorite_ids: set[int] = set()
    following_ids: set[int] = set()
    if request.user.is_authenticated:
        coupon_ids = [coupon.id for coupon in coupons]
        liked_ids = set(
            PredictionLike.objects.filter(
                user=request.user,
                prediction_id__in=coupon_ids,
            ).values_list("prediction_id", flat=True)
        )
        favorite_ids = set(
            PredictionFavorite.objects.filter(
                user=request.user,
                prediction_id__in=coupon_ids,
            ).values_list("prediction_id", flat=True)
        )
        following_ids = set(
            AnalystFollow.objects.filter(follower=request.user).values_list(
                "analyst_id",
                flat=True,
            )
        )

    cards = []
    for coupon in coupons:
        card = _prediction_card(coupon)
        if card is None:
            continue
        author = coupon.author
        card.is_liked = coupon.id in liked_ids
        card.is_favorite = coupon.id in favorite_ids
        card.is_own = request.user.is_authenticated and request.user.id == author.id
        card.is_following_author = author.id in following_ids and not card.is_own
        cards.append(card)
    return cards


def _prediction_card(coupon: PredictionCoupon):
    positions = list(getattr(coupon, "card_positions", []) or [])
    if not positions:
        return None

    item = positions[0]
    count = getattr(coupon, "positions_count", None) or len(positions)
    coefficient = _combined_coefficient(coupon)
    selection = item.selection
    market = item.market
    if count > 1:
        market = f"Экспресс · {count} игр"
        selection = f"{item.selection} + ещё {count - 1}"

    profile = getattr(coupon.author, "analyst_profile", None)
    expert_name = (
        profile.display_name
        if profile and profile.display_name
        else coupon.author.get_full_name() or coupon.author.username
    )

    return SimpleNamespace(
        id=coupon.id,
        coupon=coupon,
        match=item.match,
        market=market,
        selection=selection,
        coefficient=coefficient,
        state_status=coupon.state_status,
        created_at=coupon.published_at or coupon.created_at,
        positions_count=count,
        likes_count=getattr(coupon, "likes_count", 0),
        favorites_count=getattr(coupon, "favorites_count", 0),
        expert_name=expert_name,
        expert_initials=_initials(expert_name),
        expert_avatar_url=profile.avatar.url if profile and profile.avatar else "",
        expert_verified=bool(profile and profile.is_verified),
    )


def _combined_coefficient(coupon: PredictionCoupon) -> Decimal:
    if not coupon.total_stake:
        return Decimal("0.00")
    return (coupon.possible_payout / coupon.total_stake).quantize(Decimal("0.01"))
