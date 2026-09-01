import json
from decimal import Decimal
from types import SimpleNamespace

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import BooleanField, Case, Count, Exists, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from cabinet.models import AnalystFollow
from front.models import PredictionFavorite, PredictionLike
from front.views import _initials
from game import date_views
from game.models import Match, Prediction, PredictionCoupon
from game.services.coupon_validation import CouponMatchVerificationError
from game.views import _latest_predictions, _match_odds_tabs, _match_winner_odds
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

    active_scope = request.GET.get("scope") or PredictionMatchScope.PREMATCH
    valid_scopes = {scope for scope, _ in _tournament_scope_filters()}
    if active_scope not in valid_scopes:
        active_scope = PredictionMatchScope.PREMATCH

    allowed_sport_codes = set(tournament.allowed_sports.values_list("code", flat=True))
    active_sport = request.GET.get("sport") or "all"
    valid_sports = {sport for sport, _ in _tournament_sport_filters(allowed_sport_codes)}
    if active_sport not in valid_sports:
        active_sport = "all"

    period_start = tournament.starts_at
    period_end = tournament.ends_at
    base_matches = MatchQuery.base(period_start, period_end, active_scope)
    base_matches = _filter_tournament_allowed_sports(base_matches, allowed_sport_codes)
    base_matches = _filter_tournament_sport(base_matches, active_sport)
    if active_scope == PredictionMatchScope.WATCHED:
        base_matches = base_matches.filter(notification_watchers__user=request.user).distinct()
    base_matches = _exclude_tournament_used_matches(base_matches, tournament, participant)
    matches_queryset = MatchQuery.decorate(base_matches, request.user)

    if date_views._is_lazy_request(request) and request.GET.get("view") == "table":
        return _tournament_table_lazy_response(
            request,
            tournament=tournament,
            matches_queryset=matches_queryset,
            can_write_coupon=True,
            active_sport=active_sport,
        )

    page_obj = _tournament_page(matches_queryset, request.GET.get("page"))
    matches = list(page_obj.object_list)
    total_count = matches_queryset.count()
    _decorate_tournament_matches(matches, tournament, participant)
    table_groups = date_views._table_match_groups(
        matches_queryset,
        active_sport=active_sport,
        limit=date_views.TABLE_MATCHES_PER_SPORT,
    )

    if date_views._is_lazy_request(request):
        html = render_to_string(
            "game/includes/_match_grid_items.html",
            {
                "matches": matches,
                "can_write_coupon": True,
                "tournament_prediction_mode": True,
            },
            request=request,
        )
        return JsonResponse(
            {
                "ok": True,
                "html": html,
                "page": page_obj.number,
                "has_next": page_obj.has_next(),
                "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
            }
        )

    scope_tabs = _tournament_scope_tabs(
        request,
        tournament,
        participant=participant,
        active_scope=active_scope,
        active_sport=active_sport,
        period_start=period_start,
        period_end=period_end,
        allowed_sport_codes=allowed_sport_codes,
    )
    sport_tabs = _tournament_sport_tabs(
        request,
        tournament,
        participant=participant,
        active_scope=active_scope,
        active_sport=active_sport,
        period_start=period_start,
        period_end=period_end,
        allowed_sport_codes=allowed_sport_codes,
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
            "content_view_mode": _tournament_content_view_mode(request),
            "scope_tabs": scope_tabs,
            "sport_tabs": sport_tabs,
            "matches": matches,
            "table_grouped_matches": table_groups,
            "page_obj": page_obj,
            "can_write_coupon": True,
            "tournament_prediction_mode": True,
            "latest_predictions": _latest_predictions(),
            "draft_coupon": None,
            "coupon_match_stale_seconds": 60,
            "selected_date": timezone.localtime(period_start).date(),
            "selected_date_iso": timezone.localtime(period_start).date().isoformat(),
            "show_date_filter": False,
            "hide_date_filter": True,
            "match_list_h1": f"{tournament.title}: прогноз",
            "match_list_hero_meta": "матчей доступно",
            "total_count": total_count,
            "hero_count": total_count,
        },
    )


@require_GET
def match_odds(request, slug: str, match_id: int):
    tournament = get_object_or_404(
        Tournament.objects.prefetch_related("allowed_sports"),
        slug=slug,
        status=Tournament.Status.PUBLISHED,
    )
    participant = get_active_participant(request.user, tournament)
    if participant is None or tournament.runtime_status != "live":
        return JsonResponse({"ok": False, "error": "Турнирный прогноз недоступен."}, status=403)

    match = get_object_or_404(
        Match.objects.select_related(
            "sport",
            "league__country",
            "home_team",
            "away_team",
            "odds",
        ),
        pk=match_id,
        sync_scope=Match.SyncScope.PREMATCH,
        starts_at__gte=tournament.starts_at,
        starts_at__lte=tournament.ends_at,
    )
    if not _match_allowed_for_tournament(tournament, participant, match):
        return JsonResponse({"ok": False, "error": "Матч недоступен для этого турнира."}, status=400)

    odds_tabs = _match_odds_tabs(match)
    html = render_to_string(
        "tournaments/includes/_match_odds_panel.html",
        {
            "match": match,
            "odds_items": _flat_match_odds(odds_tabs),
            "can_write_coupon": True,
        },
        request=request,
    )
    return JsonResponse({"ok": True, "html": html})


def _flat_match_odds(odds_tabs):
    odds = []
    seen = set()
    for tab in odds_tabs:
        for section in tab.get("sections", []):
            for row in section.get("rows", []):
                for odd in row.get("odds", []):
                    key = (
                        odd.get("market"),
                        odd.get("selection"),
                        str(odd.get("coefficient")),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    odds.append(odd)
    return odds


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
    def base(period_start, period_end, active_scope: str):
        return Match.objects.filter(
            starts_at__gte=period_start,
            starts_at__lte=period_end,
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


def _exclude_tournament_used_matches(queryset, tournament: Tournament, participant: TournamentParticipant):
    used_match_ids = TournamentPredictionEntry.objects.filter(
        tournament=tournament,
        participant=participant,
        tournament_coupon__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).values("match_id")
    return queryset.exclude(id__in=used_match_ids)


def _match_allowed_for_tournament(
    tournament: Tournament,
    participant: TournamentParticipant,
    match: Match,
) -> bool:
    allowed_sport_ids = set(tournament.allowed_sports.values_list("id", flat=True))
    if allowed_sport_ids and match.sport_id not in allowed_sport_ids:
        return False
    return not TournamentPredictionEntry.objects.filter(
        tournament=tournament,
        participant=participant,
        match=match,
        tournament_coupon__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).exists()


def _tournament_content_view_mode(request) -> str:
    requested = request.GET.get("view_mode")
    return requested if requested in {"grid", "table"} else "table"


def _tournament_page(matches_queryset, raw_page):
    paginator = Paginator(matches_queryset, date_views.MATCHES_PAGE_SIZE)
    try:
        return paginator.page(raw_page or "1")
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def _tournament_table_lazy_response(
    request,
    *,
    tournament: Tournament,
    matches_queryset,
    can_write_coupon: bool,
    active_sport: str,
):
    sport_code = request.GET.get("table_sport", "").strip().lower()
    valid_sports = {sport for sport, _ in date_views.SPORT_FILTERS if sport != "all"}
    if sport_code not in valid_sports:
        return JsonResponse(
            {"ok": False, "error": "Некорректный вид спорта."},
            status=400,
        )

    groups = date_views._table_match_groups(
        matches_queryset,
        active_sport=sport_code or active_sport,
        limit=date_views._table_window_size(request.GET.get("window")),
    )
    sport_group = groups[0] if groups else None
    html = ""
    if sport_group is not None:
        sport_group["open"] = True
        html = render_to_string(
            "game/includes/_match_table_sport.html",
            {
                "tournament": tournament,
                "sport": sport_group,
                "can_write_coupon": can_write_coupon,
                "tournament_prediction_mode": True,
            },
            request=request,
        )

    return JsonResponse(
        {
            "ok": True,
            "html": html,
            "sport": sport_code,
            "window": sport_group["loaded_count"] if sport_group else 0,
            "total": sport_group["count"] if sport_group else 0,
            "has_next": bool(sport_group and sport_group["has_next"]),
            "next_window": sport_group["next_window"] if sport_group and sport_group["has_next"] else None,
        }
    )


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
    participant: TournamentParticipant,
    active_scope: str,
    active_sport: str,
    period_start,
    period_end,
    allowed_sport_codes: set[str],
) -> list[dict]:
    tabs = []
    for scope, label in _tournament_scope_filters():
        queryset = MatchQuery.base(period_start, period_end, scope)
        queryset = _filter_tournament_allowed_sports(queryset, allowed_sport_codes)
        queryset = _filter_tournament_sport(queryset, active_sport)
        if scope == PredictionMatchScope.WATCHED:
            queryset = queryset.filter(notification_watchers__user=request.user).distinct()
        queryset = _exclude_tournament_used_matches(queryset, tournament, participant)
        tabs.append(
            {
                "scope": scope,
                "label": label,
                "count": queryset.count(),
                "url": _tournament_predict_url(
                    tournament,
                    scope=scope,
                    sport=active_sport,
                ),
            }
        )
    return tabs


def _tournament_sport_tabs(
    request,
    tournament: Tournament,
    *,
    participant: TournamentParticipant,
    active_scope: str,
    active_sport: str,
    period_start,
    period_end,
    allowed_sport_codes: set[str],
) -> list[dict]:
    tabs = []
    base_queryset = MatchQuery.base(period_start, period_end, active_scope)
    base_queryset = _filter_tournament_allowed_sports(base_queryset, allowed_sport_codes)
    if active_scope == PredictionMatchScope.WATCHED:
        base_queryset = base_queryset.filter(notification_watchers__user=request.user).distinct()
    base_queryset = _exclude_tournament_used_matches(base_queryset, tournament, participant)
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
                ),
            }
        )
    return tabs


def _tournament_predict_url(tournament: Tournament, *, scope, sport) -> str:
    return (
        f"{reverse('tournaments:predict', kwargs={'slug': tournament.slug})}"
        f"?scope={scope}&sport={sport}"
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
