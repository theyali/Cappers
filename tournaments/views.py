import json
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import BooleanField, Case, Count, Exists, F, IntegerField, OuterRef, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import date_format
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from cabinet.models import AnalystFollow
from cabinet.vip import active_vip_subscriptions, annotate_vip_status, attach_vip_status_to_user
from front.models import PredictionFavorite, PredictionLike
from front.views import _initials
from game import date_views
from game.models import Match, Prediction, PredictionCoupon, Sport
from game.services.coupon_validation import CouponMatchVerificationError, CouponOddsChangedError
from game.services.bet_options import build_match_odds_tabs, build_match_winner_odds
from game.views import _latest_predictions
from notifications.models import MatchWatch
from tournaments.models import (
    Tournament,
    TournamentAchievement,
    TournamentFAQ,
    TournamentParticipant,
    TournamentPredictionEntry,
    TournamentPrize,
    TournamentResult,
    TournamentStage,
)
from tournaments.services.coupons import create_tournament_coupon
from tournaments.services.eligibility import check_tournament_eligibility
from tournaments.services.join import TournamentJoinError, get_active_participant, join_tournament
from tournaments.services.leaderboard import tournament_leaderboard
from wallets.services import InsufficientCoins, ensure_coin_wallet, format_coins, format_money


def index(request):
    now = timezone.now()
    active_sport = (request.GET.get("sport") or "all").strip().lower()
    active_filter = (request.GET.get("filter") or "all").strip().lower()
    active_sort = (request.GET.get("sort") or "start").strip().lower()
    tournaments = (
        Tournament.objects.filter(status=Tournament.Status.PUBLISHED)
        .prefetch_related(
            "achievements",
            "allowed_sports",
            Prefetch(
                "prizes",
                queryset=TournamentPrize.objects.filter(is_active=True)
                .select_related("achievement")
                .order_by("place", "sort_order", "id"),
                to_attr="active_prizes",
            ),
        )
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

    sport_tabs = _tournament_index_sport_tabs(active_sport, active_filter, active_sort)
    sport_codes = {tab.code for tab in sport_tabs if tab.code != "all"}
    if active_sport not in sport_codes:
        active_sport = "all"
    if active_sport != "all":
        tournaments = tournaments.filter(
            Q(allowed_sports__code=active_sport) | Q(allowed_sports__isnull=True)
        ).distinct()

    cards = [_tournament_card(tournament, now, request.user) for tournament in tournaments]
    if active_filter == "finished":
        cards = [card for card in cards if card.runtime_status["key"] == "finished"]
    elif active_filter == "popular":
        cards = sorted(cards, key=lambda card: card.participants_count, reverse=True)
    elif active_filter == "high_prize":
        cards = sorted(cards, key=lambda card: card.prize_total, reverse=True)
    else:
        active_filter = "all"

    if active_sort == "prize":
        cards = sorted(cards, key=lambda card: card.prize_total, reverse=True)
    elif active_sort == "popular":
        cards = sorted(cards, key=lambda card: card.participants_count, reverse=True)
    else:
        active_sort = "start"

    top_tournaments = sorted(cards, key=lambda card: card.prize_total, reverse=True)[:3]
    my_prizes = _tournament_user_prizes(request.user)
    return render(
        request,
        "tournaments/index.html",
        {
            "tournaments": cards,
            "top_tournaments": top_tournaments,
            "sport_tabs": _tournament_index_sport_tabs(active_sport, active_filter, active_sort),
            "status_filter_tabs": _tournament_index_filter_tabs(active_sport, active_filter, active_sort),
            "active_sport": active_sport,
            "active_filter": active_filter,
            "active_sort": active_sort,
            "my_prizes": my_prizes,
            "now": now,
        },
    )


def detail(request, slug: str):
    tournament = get_object_or_404(
        Tournament.objects.prefetch_related(
            "allowed_sports",
            "achievements",
            Prefetch(
                "stages",
                queryset=TournamentStage.objects.filter(is_active=True).order_by("sort_order", "id"),
                to_attr="active_stages",
            ),
            Prefetch(
                "prizes",
                queryset=TournamentPrize.objects.filter(is_active=True)
                .select_related("achievement")
                .order_by("place", "sort_order", "id"),
                to_attr="active_prizes",
            ),
        ),
        slug=slug,
        status=Tournament.Status.PUBLISHED,
    )
    participant = get_active_participant(request.user, tournament)
    leaderboard = tournament_leaderboard(tournament)
    prediction_cards = _tournament_prediction_cards(request, tournament)
    now = timezone.now()
    runtime_status = _runtime_status(tournament, now)
    allowed_sports = list(tournament.allowed_sports.all())
    participants_count = TournamentParticipant.objects.filter(
        tournament=tournament,
        status=TournamentParticipant.Status.ACTIVE,
    ).count()
    eligibility = check_tournament_eligibility(request.user, tournament)
    eligibility["entry_fee_label"] = format_coins(eligibility["entry_fee_coins"])
    eligibility["primary_reason"] = eligibility["reasons"][0] if eligibility["reasons"] else ""
    home_tab = _tournament_home_tab(
        tournament,
        runtime_status=runtime_status,
        participants_count=participants_count,
        allowed_sports=allowed_sports,
        now=now,
        eligibility=eligibility,
    )
    prizes_tab = _tournament_prizes_tab(tournament)
    about_stages = _tournament_about_stages(tournament)

    return render(
        request,
        "tournaments/detail.html",
        {
            "tournament": tournament,
            "runtime_status": runtime_status,
            "home_tab": home_tab,
            "results_tab": _tournament_results_tab(
                request,
                tournament,
                leaderboard,
            ),
            "prizes_tab": prizes_tab,
            "about_tab": _tournament_about_tab(
                tournament,
                runtime_status=runtime_status,
                participants_count=participants_count,
                allowed_sports=allowed_sports,
                eligibility=eligibility,
                prizes_tab=prizes_tab,
            ),
            "participant": participant,
            "eligibility": eligibility,
            "participants_count": participants_count,
            "about_stages": about_stages,
            "leaderboard": leaderboard[:20],
            "prediction_cards": prediction_cards,
            "allowed_sports": allowed_sports,
            "achievements": list(tournament.achievements.all()),
            "breadcrumbs": [
                {"title": "Главная", "url": reverse("front:index")},
                {"title": "Турниры", "url": reverse("tournaments:index")},
                {"title": tournament.title},
            ],
        },
    )


@require_GET
def results(request, slug: str):
    tournament = get_object_or_404(
        Tournament.objects.prefetch_related("allowed_sports", "achievements"),
        slug=slug,
        status=Tournament.Status.PUBLISHED,
    )
    leaderboard = tournament_leaderboard(tournament)
    results_tab = _tournament_results_tab(request, tournament, leaderboard)
    html = render_to_string(
        "tournaments/includes/_results_tab.html",
        {
            "tournament": tournament,
            "results_tab": results_tab,
        },
        request=request,
    )
    return JsonResponse(
        {
            "ok": True,
            "html": html,
            "page": results_tab["page_obj"].number,
            "pages": results_tab["page_obj"].paginator.num_pages,
            "total": results_tab["total_count"],
        }
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
    matches_queryset = MatchQuery.decorate(base_matches, request.user)

    if date_views._is_lazy_request(request) and request.GET.get("view") == "table":
        return _tournament_table_lazy_response(
            request,
            tournament=tournament,
            participant=participant,
            matches_queryset=matches_queryset,
            can_write_coupon=True,
            active_sport=active_sport,
        )

    page_obj = _tournament_page(matches_queryset, request.GET.get("page"))
    matches = list(page_obj.object_list)
    total_count = matches_queryset.count()
    used_match_ids = _tournament_used_match_ids(tournament, participant)
    _decorate_tournament_matches(
        matches,
        tournament,
        participant,
        used_match_ids=used_match_ids,
    )
    table_groups = date_views._table_match_groups(
        matches_queryset,
        active_sport=active_sport,
        limit=date_views.TABLE_MATCHES_PER_SPORT,
    )
    _decorate_tournament_table_groups(
        table_groups,
        tournament,
        participant,
        used_match_ids=used_match_ids,
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
            "home_team__country",
            "away_team__country",
            "odds",
        ),
        pk=match_id,
        sync_scope=Match.SyncScope.PREMATCH,
        starts_at__gte=tournament.starts_at,
        starts_at__lte=tournament.ends_at,
    )
    if not _match_allowed_for_tournament(tournament, participant, match):
        return JsonResponse({"ok": False, "error": "Матч недоступен для этого турнира."}, status=400)

    odds_tabs = build_match_odds_tabs(match)
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
    except InsufficientCoins as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=402)
    except CouponMatchVerificationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)
    except CouponOddsChangedError as exc:
        return JsonResponse(
            {"ok": False, "error": _validation_message(exc), "odds_changed": exc.changes},
            status=409,
        )
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

    coin_wallet = ensure_coin_wallet(request.user)
    return JsonResponse(
        {
            "ok": True,
            "coupon_id": coupon.id,
            "tournament_coupon_id": tournament_coupon.id,
            "tournament_id": tournament.id,
            "message": "Прогноз турнира опубликован.",
            "coupon_url": reverse("front:prediction_detail", kwargs={"prediction_id": coupon.id}),
            "coin_balance": coin_wallet.balance,
            "coin_balance_display": format_coins(coin_wallet.balance),
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
            queryset.select_related("sport", "league__country", "home_team__country", "away_team__country", "odds")
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
                        predictions__coupon__audience=PredictionCoupon.Audience.FREE,
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
    participant: TournamentParticipant,
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
        used_match_ids = _tournament_used_match_ids(tournament, participant)
        _decorate_tournament_table_groups(
            [sport_group],
            tournament,
            participant,
            used_match_ids=used_match_ids,
        )
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


def _tournament_used_match_ids(
    tournament: Tournament,
    participant: TournamentParticipant,
) -> set[int]:
    return set(
        TournamentPredictionEntry.objects.filter(
            tournament=tournament,
            participant=participant,
            tournament_coupon__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        ).values_list("match_id", flat=True)
    )


def _decorate_tournament_matches(
    matches: list[Match],
    tournament: Tournament,
    participant: TournamentParticipant,
    *,
    used_match_ids: set[int] | None = None,
) -> None:
    if used_match_ids is None:
        used_match_ids = _tournament_used_match_ids(tournament, participant)
    for match in matches:
        match.coupon_odds = build_match_winner_odds(match)
        match.tournament_match_used = match.id in used_match_ids


def _decorate_tournament_table_groups(
    table_groups: list[dict],
    tournament: Tournament,
    participant: TournamentParticipant,
    *,
    used_match_ids: set[int] | None = None,
) -> None:
    if used_match_ids is None:
        used_match_ids = _tournament_used_match_ids(tournament, participant)
    for sport_group in table_groups:
        for league_group in sport_group.get("leagues", []):
            _decorate_tournament_matches(
                list(league_group.get("items", [])),
                tournament,
                participant,
                used_match_ids=used_match_ids,
            )


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
    base_queryset = MatchQuery.base(period_start, period_end, active_scope)
    base_queryset = _filter_tournament_allowed_sports(base_queryset, allowed_sport_codes)
    if active_scope == PredictionMatchScope.WATCHED:
        base_queryset = base_queryset.filter(notification_watchers__user=request.user).distinct()
    base_queryset = _exclude_tournament_used_matches(base_queryset, tournament, participant)

    count_rows = list(
        base_queryset.values("sport__code")
        .annotate(total=Count("id", distinct=True))
        .order_by()
    )
    sport_counts = {
        row["sport__code"]: row["total"]
        for row in count_rows
        if row["sport__code"]
    }
    all_count = sum(row["total"] for row in count_rows)

    tabs = []
    for sport, label in _tournament_sport_filters(allowed_sport_codes):
        tabs.append(
            {
                "code": sport,
                "label": label,
                "count": all_count if sport == "all" else sport_counts.get(sport, 0),
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


def _tournament_index_query(**params) -> str:
    clean = {
        key: value
        for key, value in params.items()
        if value and value != "all" and not (key == "sort" and value == "start")
    }
    query = urlencode(clean)
    base_url = reverse("tournaments:index")
    return f"{base_url}?{query}" if query else base_url


def _tournament_index_sport_tabs(active_sport: str, active_filter: str, active_sort: str):
    core = [
        ("football", "Футбол", "⚽"),
        ("basketball", "Баскетбол", "🏀"),
        ("tennis", "Теннис", "🎾"),
        ("hockey", "Хоккей", "🏒"),
    ]
    sports = list(Sport.objects.filter(code__in=[code for code, _, _ in core]).only("code", "name", "name_ru"))
    by_code = {sport.code: sport for sport in sports}
    tabs = [
        SimpleNamespace(
            code="all",
            label="Все виды",
            icon="🏆",
            is_active=active_sport == "all",
            url=_tournament_index_query(filter=active_filter, sort=active_sort),
        )
    ]
    for code, fallback_label, icon in core:
        sport = by_code.get(code)
        label = (sport.name_ru or sport.name) if sport else fallback_label
        tabs.append(
            SimpleNamespace(
                code=code,
                label=label,
                icon=icon,
                is_active=active_sport == code,
                url=_tournament_index_query(sport=code, filter=active_filter, sort=active_sort),
            )
        )
    return tabs


def _tournament_index_filter_tabs(active_sport: str, active_filter: str, active_sort: str):
    filters = [
        ("all", "Все", ""),
        ("popular", "Популярные", "🔥"),
        ("finished", "Завершенные", "◷"),
        ("high_prize", "С высоким призом", "🏆"),
    ]
    return [
        SimpleNamespace(
            key=key,
            label=label,
            icon=icon,
            is_active=active_filter == key,
            url=_tournament_index_query(sport=active_sport, filter=key, sort=active_sort),
        )
        for key, label, icon in filters
    ]


def _tournament_user_prizes(user):
    if not getattr(user, "is_authenticated", False):
        return None
    prizes = TournamentResult.objects.filter(participant__user=user, prize_amount__gt=0)
    summary = prizes.aggregate(total=Sum("prize_amount"))
    total = summary["total"] or Decimal("0")
    count = prizes.count()
    if not count or total <= 0:
        return None
    return SimpleNamespace(
        count=count,
        total=total,
        url=f"{reverse('cabinet:profile')}?tab=earnings",
    )


def _tournament_card(tournament: Tournament, now, user=None) -> SimpleNamespace:
    allowed_sports = list(tournament.allowed_sports.all())
    first_sport = allowed_sports[0] if allowed_sports else None
    prizes = _active_prizes_by_place(tournament)
    prize_total = sum((prize.money_amount or Decimal("0") for prize in prizes), Decimal("0"))
    coins_total = sum((int(prize.coins_amount or 0) for prize in prizes), 0)
    vip_days_max = max((int(prize.vip_days or 0) for prize in prizes), default=0)
    eligibility = check_tournament_eligibility(user, tournament)
    return SimpleNamespace(
        tournament=tournament,
        runtime_status=_runtime_status(tournament, now),
        participants_count=getattr(tournament, "participants_count", 0),
        coupons_count=getattr(tournament, "coupons_count", 0),
        prize_total=prize_total,
        coins_total=coins_total,
        vip_days_max=vip_days_max,
        prize_places=[_tournament_card_prize_place(prize) for prize in prizes[:3]],
        access_badges=_tournament_access_badges(tournament, eligibility),
        reward_badges=_tournament_card_reward_badges(coins_total, vip_days_max, prizes),
        eligibility_badge=_tournament_card_eligibility_badge(user, eligibility),
        sport_code=(first_sport.code if first_sport else "all"),
        sport_label=(first_sport.name_ru or first_sport.name if first_sport else "Все виды спорта"),
        sport_icon=_tournament_sport_icon(first_sport.code if first_sport else "all"),
    )


def _tournament_card_prize_place(prize: TournamentPrize) -> SimpleNamespace:
    amount = prize.money_amount or Decimal("0")
    if amount > 0:
        label = f"{format_money(amount)} ₽"
        reward_kind = "money"
    elif prize.coins_amount:
        label = format_coins(prize.coins_amount)
        reward_kind = "coins"
    elif prize.vip_days:
        label = f"VIP {prize.vip_days} дн."
        reward_kind = "vip"
    elif prize.achievement:
        label = prize.achievement.title
        reward_kind = "achievement"
    else:
        label = prize.title or "Приз"
        reward_kind = "reward"
    return SimpleNamespace(place=prize.place, label=label, reward_kind=reward_kind)


def _tournament_card_reward_badges(coins_total: int, vip_days_max: int, prizes: list[TournamentPrize]) -> list[dict]:
    badges = []
    if coins_total:
        badges.append({"label": f"+ {format_coins(coins_total)}", "tone": "coins"})
    if vip_days_max:
        badges.append({"label": f"VIP до {vip_days_max} дн.", "tone": "vip"})
    if any(prize.achievement_id for prize in prizes):
        badges.append({"label": "Достижение", "tone": "achievement"})
    return badges


def _tournament_card_eligibility_badge(user, eligibility: dict) -> dict:
    if not getattr(user, "is_authenticated", False):
        return {"label": "Войдите для проверки", "tone": "neutral"}
    if eligibility.get("allowed"):
        return {"label": "Вы подходите", "tone": "ok"}
    reason = (eligibility.get("reasons") or ["Условия не выполнены."])[0]
    return {"label": reason.rstrip("."), "tone": "danger"}


def _tournament_sport_icon(code: str) -> str:
    return {
        "football": "⚽",
        "basketball": "🏀",
        "tennis": "🎾",
        "hockey": "🏒",
    }.get(code, "🏆")


def _tournament_home_tab(
    tournament: Tournament,
    *,
    runtime_status: dict,
    participants_count: int,
    allowed_sports: list[Sport],
    now,
    eligibility: dict,
) -> dict:
    allowed_sports_label = (
        ", ".join(sport.name_ru or sport.name for sport in allowed_sports)
        if allowed_sports
        else "все виды спорта"
    )
    home_prizes = _tournament_home_prize_rows(tournament)
    prize_total = sum((prize.amount for prize in home_prizes if prize.money), Decimal("0"))
    first_sport = allowed_sports[0] if allowed_sports else None
    achievements = _tournament_achievement_list(tournament)
    first_place_achievement = next(
        (achievement for achievement in achievements if achievement.kind == TournamentAchievement.Kind.FIRST_PLACE),
        achievements[0] if achievements else None,
    )

    if runtime_status["key"] == "finished":
        date_hint = "Турнир завершён"
    else:
        delta = tournament.ends_at - now
        days_left = max(0, delta.days)
        date_hint = f"Осталось {days_left} дн." if days_left else runtime_status["target_label"]
    registration_open = now < tournament.starts_at
    if runtime_status["key"] == "finished":
        registration_note = "Турнир завершён."
    elif not registration_open:
        registration_note = "Регистрация на турнир завершена."
    else:
        registration_note = ""

    return {
        "sport_icon": _tournament_sport_icon(first_sport.code if first_sport else "all"),
        "sport_label": (first_sport.name_ru or first_sport.name if first_sport else "Все виды спорта"),
        "hero_icon_url": tournament.hero_icon.url if tournament.hero_icon else "",
        "prize_total": prize_total,
        "date_hint": date_hint,
        "registration_open": registration_open,
        "registration_note": registration_note,
        "rules": _default_participation_rules(tournament),
        "format_rules": _default_format_rules(
            tournament,
            allowed_sports_label=allowed_sports_label,
        ),
        "eligibility": _tournament_eligibility_summary(tournament, eligibility),
        "first_place_achievement": first_place_achievement,
        "achievements": achievements[:3],
        "prizes": home_prizes,
        "stats": [
            {
                "icon": "status",
                "label": "Статус",
                "value": runtime_status["label"],
                "tone": runtime_status["key"],
            },
            {
                "icon": "users",
                "label": "Участники",
                "value": participants_count,
                "caption": "капперов",
            },
            {
                "icon": "coins",
                "label": "Призовой фонд",
                "value": prize_total,
                "money": True,
            },
            {
                "icon": "chart",
                "label": "Мин. коэффициент",
                "value": f"{tournament.min_coefficient:.2f}",
            },
            {
                "icon": "calendar",
                "label": "Даты турнира",
                "value": "",
                "date": True,
                "caption": date_hint,
            },
        ],
    }


def _tournament_home_prize_rows(tournament: Tournament) -> list[SimpleNamespace]:
    prizes = _active_prizes_by_place(tournament)
    if prizes:
        rows = [_tournament_home_prize_row(prize) for prize in prizes]
    else:
        rows = _legacy_home_prize_rows(tournament)

    max_value = max((row.metric_value for row in rows), default=Decimal("1"))
    if max_value <= 0:
        max_value = Decimal("1")
    for row in rows:
        row.width = int((row.metric_value / max_value) * 100) if row.metric_value else 0
    return rows


def _tournament_home_prize_row(prize: TournamentPrize) -> SimpleNamespace:
    money_amount = prize.money_amount or Decimal("0")
    coins_amount = int(prize.coins_amount or 0)
    vip_days = int(prize.vip_days or 0)
    if money_amount > 0:
        value_label = f"{format_money(money_amount)} ₽"
        reward_kind = "money"
        metric_value = money_amount
    elif coins_amount:
        value_label = format_coins(coins_amount)
        reward_kind = "coins"
        metric_value = Decimal(coins_amount)
    elif vip_days:
        value_label = f"VIP {vip_days} дн."
        reward_kind = "vip"
        metric_value = Decimal(vip_days)
    elif prize.achievement:
        value_label = prize.achievement.title
        reward_kind = "achievement"
        metric_value = Decimal("1")
    else:
        value_label = prize.title or "Приз"
        reward_kind = "reward"
        metric_value = Decimal("1")

    return SimpleNamespace(
        place=prize.place,
        label=f"{prize.place} место",
        amount=money_amount,
        money=money_amount > 0,
        value_label=value_label,
        reward_kind=reward_kind,
        coins_amount=coins_amount,
        metric_value=metric_value,
        width=0,
    )


def _legacy_home_prize_rows(tournament: Tournament) -> list[SimpleNamespace]:
    rows = []
    for place, amount in (
        (1, tournament.prize_first or Decimal("0")),
        (2, tournament.prize_second or Decimal("0")),
        (3, tournament.prize_third or Decimal("0")),
    ):
        rows.append(
            SimpleNamespace(
                place=place,
                label=f"{place} место",
                amount=amount,
                money=True,
                value_label=f"{format_money(amount)} ₽",
                reward_kind="money",
                metric_value=amount,
                width=0,
            )
        )
    return rows


def _tournament_eligibility_summary(tournament: Tournament, eligibility: dict) -> dict:
    authenticated = any(rule.get("code") != "auth" for rule in eligibility.get("rules", [])) or not any(
        rule.get("code") == "auth" for rule in eligibility.get("rules", [])
    )
    rules = (
        _tournament_personal_eligibility_rows(eligibility)
        if authenticated
        else _tournament_public_eligibility_rows(tournament)
    )
    if not rules:
        rules = [
            {
                "title": "Открытое участие",
                "meta": "Дополнительных условий нет",
                "state": "neutral",
            }
        ]

    return {
        "badges": _tournament_access_badges(tournament, eligibility),
        "status": _tournament_eligibility_status(eligibility, authenticated=authenticated),
        "mode_label": (
            "Достаточно выполнить одно условие"
            if tournament.eligibility_mode == Tournament.EligibilityMode.ANY and len(rules) > 1
            else "Нужно выполнить все условия"
        ),
        "rules": rules,
    }


def _tournament_access_badges(tournament: Tournament, eligibility: dict) -> list[dict]:
    badges = [
        {
            "label": tournament.get_access_type_display(),
            "tone": "warning" if tournament.access_type == Tournament.AccessType.CLOSED else "ok",
        }
    ]
    if tournament.entry_type == Tournament.EntryType.PAID:
        badges.append(
            {
                "label": f"Вход: {format_coins(eligibility.get('entry_fee_coins', 0))}",
                "tone": "paid",
                "coin_amount": eligibility.get("entry_fee_coins", 0),
            }
        )
    else:
        badges.append({"label": "Бесплатный вход", "tone": "ok"})
    if tournament.analysts_only:
        badges.append({"label": "Только капперы", "tone": "neutral"})
    if tournament.vip_only:
        badges.append({"label": "Только VIP", "tone": "warning"})
    if tournament.new_users_only:
        badges.append({"label": "Для новых пользователей", "tone": "neutral"})
    return badges


def _tournament_eligibility_status(eligibility: dict, *, authenticated: bool) -> dict:
    if not authenticated:
        return {
            "label": "Войдите, чтобы проверить доступ",
            "caption": "Условия турнира можно посмотреть заранее.",
            "tone": "neutral",
        }
    if eligibility.get("allowed"):
        return {
            "label": "Вы подходите",
            "caption": "Можно принять участие в турнире.",
            "tone": "ok",
        }
    reason = eligibility.get("primary_reason") or (eligibility.get("reasons") or ["Условия не выполнены."])[0]
    return {
        "label": "Не подходите",
        "caption": reason,
        "tone": "danger",
    }


def _tournament_personal_eligibility_rows(eligibility: dict) -> list[dict]:
    rows = []
    for rule in eligibility.get("rules", []):
        if rule.get("code") == "auth":
            continue
        rows.append(
            {
                "title": rule.get("title") or "Условие",
                "meta": _eligibility_rule_meta(rule),
                "meta_coin": rule.get("code") == "entry_fee_coins",
                "state": "passed" if rule.get("passed") else "failed",
                "description": rule.get("description") or "",
            }
        )
    return rows


def _tournament_public_eligibility_rows(tournament: Tournament) -> list[dict]:
    rows = []
    if tournament.analysts_only:
        rows.append({"title": "Статус каппера", "meta": "обязательно", "state": "neutral"})
    if tournament.vip_only:
        rows.append({"title": "VIP-статус", "meta": "обязательно", "state": "neutral"})
    if tournament.new_users_only:
        rows.append({"title": "Новый пользователь", "meta": "обязательно", "state": "neutral"})
    if tournament.entry_type == Tournament.EntryType.PAID:
        rows.append(
            {
                "title": "Коины для участия",
                "meta": f"нужно {format_coins(tournament.entry_fee_coins)}",
                "meta_coin": True,
                "state": "neutral",
            }
        )
    if tournament.min_user_predictions:
        rows.append(
            {
                "title": "Опубликованные прогнозы",
                "meta": f"нужно {tournament.min_user_predictions}",
                "state": "neutral",
            }
        )
    if tournament.min_user_wins:
        rows.append(
            {
                "title": "Выигранные прогнозы",
                "meta": f"нужно {tournament.min_user_wins}",
                "state": "neutral",
            }
        )
    rows.extend(_configured_public_eligibility_rows(tournament))
    return rows


def _configured_public_eligibility_rows(tournament: Tournament) -> list[dict]:
    rows = []
    for rule in tournament.eligibility_rules.filter(is_active=True).select_related("sport").order_by("sort_order", "id"):
        title = rule.title or rule.get_rule_type_display()
        if rule.sport_id:
            title = f"{title} ({rule.sport.name_ru or rule.sport.name})"
        meta = (
            "обязательно"
            if rule.rule_type in ("vip_status", "new_user")
            else _operator_requirement_label(rule.operator, rule.value)
        )
        rows.append(
            {
                "title": title,
                "meta": meta,
                "state": "neutral",
                "description": rule.description,
            }
        )
    return rows


def _operator_requirement_label(operator: str, value: int) -> str:
    if operator == "lte":
        return f"не больше {value}"
    if operator == "eq":
        return f"ровно {value}"
    return f"нужно {value}"


def _eligibility_rule_meta(rule: dict) -> str:
    required = rule.get("required")
    current = rule.get("current")
    if isinstance(required, bool):
        return "выполнено" if current else "не выполнено"
    if isinstance(current, bool):
        return "выполнено" if current else "не выполнено"
    if rule.get("code") == "entry_fee_coins":
        return f"{format_coins(current)} / {format_coins(required)}"
    return f"{current} / {required}"


def _default_participation_rules(tournament: Tournament) -> list[str]:
    rules = [
        "Открытый турнир" if tournament.access_type == Tournament.AccessType.OPEN else "Закрытый турнир",
        (
            "Платное участие"
            if tournament.entry_type == Tournament.EntryType.PAID
            else "Бесплатное участие"
        ),
    ]
    if tournament.analysts_only:
        rules.append("Участвовать могут только капперы")
    if tournament.vip_only:
        rules.append("Нужен активный VIP-статус")
    if tournament.new_users_only:
        rules.append("Турнир доступен только новым пользователям")
    if tournament.min_user_predictions:
        rules.append(f"Минимум опубликованных прогнозов — {tournament.min_user_predictions}")
    if tournament.min_user_wins:
        rules.append(f"Минимум выигранных прогнозов — {tournament.min_user_wins}")
    if tournament.eligibility_sport_id:
        sport_name = tournament.eligibility_sport.name_ru or tournament.eligibility_sport.name
        rules.append(f"Активность для допуска считается по спорту: {sport_name}")
    for rule in _configured_public_eligibility_rows(tournament):
        meta = f": {rule['meta']}" if rule.get("meta") else ""
        rules.append(f"{rule['title']}{meta}")
    return rules


def _default_format_rules(tournament: Tournament, *, allowed_sports_label: str) -> list[str]:
    return [
        f"Прогнозы только на матчи: {allowed_sports_label}",
        f"Минимальный коэффициент прогноза — {tournament.min_coefficient:.2f}",
        f"Тип прогноза: {tournament.get_coupon_type_rule_display()}",
        (
            f"Минимальная уверенность прогноза — {tournament.min_confidence}%"
            if tournament.min_confidence
            else "Уверенность прогноза без ограничения"
        ),
        "Рейтинг формируется по ROI",
        "Учитываются только рассчитанные прогнозы",
        "При равенстве выше участник с большим числом прибыльных ставок",
        "Результаты обновляются автоматически",
    ]


def _tournament_about_stages(tournament: Tournament) -> list[SimpleNamespace]:
    stages = list(getattr(tournament, "active_stages", []) or [])
    if stages:
        return [
            SimpleNamespace(
                number=index,
                title=stage.title,
                period=stage.period,
                description=stage.description,
            )
            for index, stage in enumerate(stages, start=1)
        ]

    starts_at = timezone.localtime(tournament.starts_at)
    ends_at = timezone.localtime(tournament.ends_at)
    starts_label = date_format(starts_at, "j E")
    ends_label = date_format(ends_at, "j E")

    return [
        SimpleNamespace(
            number=1,
            title="Регистрация",
            period=starts_label,
            description="Формирование списка участников.",
        ),
        SimpleNamespace(
            number=2,
            title="Основной этап",
            period=f"{starts_label} — {ends_label}",
            description="Участники публикуют прогнозы, идет подсчет результатов.",
        ),
        SimpleNamespace(
            number=3,
            title="Подведение итогов",
            period="после завершения",
            description="Проверка результатов и расчет призов.",
        ),
        SimpleNamespace(
            number=4,
            title="Награждение",
            period="после итогов",
            description="Выплата призов и присвоение статусов.",
        ),
    ]


def _tournament_prizes_tab(tournament: Tournament) -> dict:
    achievements = _tournament_achievement_list(tournament)
    achievement_by_place = _achievement_by_prize_place(achievements)
    rows = [
        _tournament_prize_row(
            prize,
            achievement=prize.achievement or achievement_by_place.get(prize.place),
        )
        for prize in _active_prizes_by_place(tournament)
    ]
    first_prize = next((row for row in rows if row.place == 1), None)
    feature_achievement = (
        first_prize.achievement
        if first_prize and first_prize.achievement
        else (achievements[0] if achievements else None)
    )

    return {
        "rows": rows,
        "first_prize": first_prize,
        "first_place_achievement": first_prize.achievement if first_prize else None,
        "feature_achievement": feature_achievement,
        "feature_items": _tournament_first_prize_feature_items(first_prize),
        "benefits": _tournament_prize_benefits(rows),
        "notes": _tournament_prize_notes(tournament),
    }


def _tournament_achievement_list(tournament: Tournament) -> list[TournamentAchievement]:
    return sorted(
        list(tournament.achievements.all()),
        key=lambda achievement: (achievement.sort_order, achievement.id),
    )


def _active_prizes_by_place(tournament: Tournament) -> list[TournamentPrize]:
    return sorted(
        list(getattr(tournament, "active_prizes", []) or []),
        key=lambda prize: (prize.place, prize.sort_order, prize.id),
    )


def _achievement_by_prize_place(achievements: list[TournamentAchievement]) -> dict[int, TournamentAchievement]:
    kind_by_place = {
        1: TournamentAchievement.Kind.FIRST_PLACE,
        2: TournamentAchievement.Kind.SECOND_PLACE,
        3: TournamentAchievement.Kind.THIRD_PLACE,
    }
    achievement_by_kind = {}
    for achievement in achievements:
        achievement_by_kind.setdefault(achievement.kind, achievement)
    return {
        place: achievement_by_kind[kind]
        for place, kind in kind_by_place.items()
        if kind in achievement_by_kind
    }


def _tournament_prize_row(prize: TournamentPrize, *, achievement: TournamentAchievement | None = None) -> SimpleNamespace:
    bonus_parts = []
    if prize.title:
        bonus_parts.append(prize.title)
    if prize.vip_days:
        bonus_parts.append(f"VIP на {prize.vip_days} дн.")
    if prize.coins_amount:
        bonus_parts.append(format_coins(prize.coins_amount))
    if achievement:
        bonus_parts.append(achievement.title)

    return SimpleNamespace(
        place=prize.place,
        label=f"{prize.place} место",
        money_amount=prize.money_amount or Decimal("0"),
        coins_amount=prize.coins_amount,
        coins_label=format_coins(prize.coins_amount) if prize.coins_amount else "—",
        vip_days=prize.vip_days,
        vip_label=f"{prize.vip_days} дн." if prize.vip_days else "—",
        achievement=achievement,
        achievement_label=achievement.title if achievement else "—",
        title=prize.title,
        description=prize.description,
        feature_items=_tournament_first_prize_feature_items(prize, achievement=achievement),
        bonus=", ".join(bonus_parts) if bonus_parts else "—",
        has_bonus=bool(bonus_parts),
        tone=_tournament_prize_tone(prize.place),
    )


def _tournament_first_prize_feature_items(prize, *, achievement=None) -> list[dict]:
    if not prize:
        return []
    items = []
    if prize.money_amount:
        items.append(
            {
                "title": f"{format_money(prize.money_amount)} ₽",
                "caption": "Денежный приз на основной счет",
            }
        )
    if prize.coins_amount:
        items.append(
            {
                "kind": "coins",
                "title": format_coins(prize.coins_amount),
                "caption": "Дополнительное начисление на виртуальный счет",
            }
        )
    if prize.vip_days:
        items.append(
            {
                "title": f"VIP на {prize.vip_days} дн.",
                "caption": "Доступ к VIP-возможностям платформы",
            }
        )
    achievement = achievement or prize.achievement
    if achievement:
        items.append(
            {
                "title": achievement.title,
                "caption": achievement.description or "Достижение в публичном профиле",
            }
        )
    if prize.description:
        items.append({"title": prize.title or "Бонус", "caption": prize.description})
    return items


def _tournament_prize_benefits(prizes) -> list[dict]:
    prizes = list(prizes or [])
    if not prizes:
        return []
    benefits = []
    if any(prize.achievement for prize in prizes):
        benefits.append({"icon": "crown", "label": "Выделенный статус в рейтинге"})
    if any(prize.vip_days for prize in prizes):
        benefits.append({"icon": "star", "label": "Доступ к VIP-разделам"})
    if any(prize.coins_amount for prize in prizes):
        benefits.append({"icon": "coins", "label": "Коины для платных прогнозов и турниров"})
    if any(prize.money_amount for prize in prizes):
        benefits.append({"icon": "wallet", "label": "Денежный приз на баланс"})
    return benefits[:4]


def _tournament_prize_notes(tournament: Tournament) -> list[dict]:
    return [
        {
            "icon": "clock",
            "title": "Срок выплаты",
            "text": tournament.reward_payout_text
            or "Призы начисляются в течение 24 часов после окончания турнира.",
        },
        {
            "icon": "wallet",
            "title": "Куда начисляются деньги",
            "text": tournament.reward_wallet_text
            or "Денежный приз поступает на основной игровой счет КапперХаб.",
        },
        {
            "icon": "coins",
            "title": "Куда начисляются коины",
            "text": tournament.reward_coins_wallet_text
            or "Призовые коины поступают на виртуальный счет пользователя.",
        },
        {
            "icon": "rules",
            "title": "Призовая зона",
            "text": tournament.reward_rules_text
            or f"Для попадания в призовую зону прогнозы должны учитывать минимальный коэффициент {tournament.min_coefficient:.2f}.",
        },
    ]


def _tournament_about_tab(
    tournament: Tournament,
    *,
    runtime_status: dict,
    participants_count: int,
    allowed_sports: list[Sport],
    eligibility: dict,
    prizes_tab: dict,
) -> dict:
    prize_rows = prizes_tab.get("rows") or []
    money_total = sum((row.money_amount for row in prize_rows), Decimal("0"))
    coins_total = sum((int(row.coins_amount or 0) for row in prize_rows), 0)
    vip_prizes = sum((1 for row in prize_rows if row.vip_days), 0)
    allowed_sports_label = _allowed_sports_label(allowed_sports)
    access_text = _about_access_text(tournament, eligibility)
    entry_text = _about_entry_text(tournament)

    return {
        "stats": {
            "date_title": f"{date_format(timezone.localtime(tournament.starts_at), 'j E')} — {date_format(timezone.localtime(tournament.ends_at), 'j E')}",
            "date_caption": f"{timezone.localtime(tournament.ends_at):%Y} года",
            "participants_title": str(participants_count),
            "participants_caption": "капперов" if tournament.analysts_only else "участников",
            "prize_title": f"{format_money(money_total)} ₽" if money_total > 0 else "Призы",
            "prize_caption": _about_prize_caption(money_total, coins_total, vip_prizes),
            "entry_title": entry_text["title"],
            "entry_caption": entry_text["caption"],
            "entry_coin_amount": entry_text.get("coin_amount", 0),
        },
        "info_cards": [
            {
                "icon": "users",
                "tone": "",
                "title": "Кто может участвовать",
                "text": access_text,
            },
            {
                "icon": "chart",
                "tone": "",
                "title": "Как считаются результаты",
                "text": "Рейтинг формируется по ROI и прибыли. Учитываются только рассчитанные прогнозы.",
            },
            {
                "icon": "shield",
                "tone": "is-yellow",
                "title": "Правила прогнозов",
                "text": _about_prediction_rules_text(tournament, allowed_sports_label),
            },
            {
                "icon": "wallet",
                "tone": "",
                "title": "Вход в турнир",
                "text": entry_text["text"],
            },
            {
                "icon": "gift",
                "tone": "",
                "title": "Какие призы выдаются",
                "text": _about_prizes_text(prize_rows, money_total, coins_total, vip_prizes),
            },
        ],
        "faq": _tournament_faq_items(),
        "status_label": runtime_status["label"],
    }


def _tournament_faq_items() -> list[TournamentFAQ]:
    return list(TournamentFAQ.objects.filter(is_active=True).order_by("sort_order", "id"))


def _allowed_sports_label(allowed_sports: list[Sport]) -> str:
    if not allowed_sports:
        return "всем видам спорта"
    return ", ".join(sport.name_ru or sport.name for sport in allowed_sports)


def _about_access_text(tournament: Tournament, eligibility: dict) -> str:
    parts = [tournament.get_access_type_display().lower()]
    if tournament.analysts_only:
        parts.append("только для капперов")
    else:
        parts.append("для всех пользователей")
    if tournament.vip_only:
        parts.append("нужен VIP")
    if tournament.new_users_only:
        parts.append("только новые пользователи")
    if tournament.eligibility_mode == Tournament.EligibilityMode.ANY and eligibility.get("condition_rules"):
        parts.append("достаточно выполнить одно активное условие")
    elif eligibility.get("condition_rules"):
        parts.append("нужно выполнить все активные условия")
    return ". ".join(part[:1].upper() + part[1:] for part in parts) + "."


def _about_entry_text(tournament: Tournament) -> dict:
    if tournament.entry_type == Tournament.EntryType.PAID:
        price = format_coins(tournament.entry_fee_coins)
        return {
            "title": price,
            "caption": "стоимость участия",
            "coin_amount": tournament.entry_fee_coins,
            "text": "Участие платное: при входе списывается сумма с виртуального счета.",
        }
    return {
        "title": "Бесплатный",
        "caption": "без списания",
        "coin_amount": 0,
        "text": "Участие бесплатное: виртуальная валюта за вход не списывается.",
    }


def _about_prize_caption(money_total: Decimal, coins_total: int, vip_prizes: int) -> str:
    parts = []
    if money_total > 0:
        parts.append("денежные призы")
    if coins_total > 0:
        parts.append("коины")
    if vip_prizes:
        parts.append("VIP")
    return ", ".join(parts) if parts else "призы настраиваются"


def _about_prediction_rules_text(tournament: Tournament, allowed_sports_label: str) -> str:
    return (
        f"Матчи: {allowed_sports_label}. Минимальный коэффициент — "
        f"{tournament.min_coefficient:.2f}. Тип прогноза: {tournament.get_coupon_type_rule_display().lower()}."
    )


def _about_prizes_text(prize_rows: list, money_total: Decimal, coins_total: int, vip_prizes: int) -> str:
    if not prize_rows:
        return "Призы пока не добавлены в админке."
    parts = []
    if money_total > 0:
        parts.append(f"денежный фонд {format_money(money_total)} ₽")
    if coins_total > 0:
        parts.append("призовые начисления на виртуальный счет")
    if vip_prizes:
        parts.append("VIP-статусы")
    achievements_count = sum(1 for row in prize_rows if row.achievement)
    if achievements_count:
        parts.append("достижения")
    return "Лучшие участники получают " + ", ".join(parts) + "."


def _tournament_prize_tone(place: int) -> str:
    return {
        1: "gold",
        2: "silver",
        3: "bronze",
    }.get(place, "gray")


def _tournament_results_tab(request, tournament: Tournament, leaderboard: list[dict]) -> dict:
    active_filter = (request.GET.get("filter") or "all").strip().lower()
    query = (request.GET.get("q") or "").strip()
    country = (request.GET.get("country") or "all").strip().lower()
    per_page = _positive_int(request.GET.get("per_page"), default=10)
    if per_page not in (10, 20, 50):
        per_page = 10

    vip_user_ids = set(
        active_vip_subscriptions().filter(
            user_id__in=[row["user"].id for row in leaderboard]
        ).values_list("user_id", flat=True)
    )
    rows = [_tournament_result_row(row, vip_user_ids=vip_user_ids) for row in leaderboard]
    if active_filter == "vip":
        rows = [row for row in rows if row["is_vip"]]
    else:
        active_filter = "all"

    if query:
        needle = query.lower()
        rows = [
            row for row in rows
            if needle in row["name"].lower() or needle in row["username"].lower()
        ]

    page_obj = _paginate_list(rows, request.GET.get("page"), per_page)
    updates = _tournament_result_updates(rows)
    top_rows = rows[:3]

    return {
        "rows": list(page_obj.object_list),
        "top_rows": top_rows,
        "updates": updates,
        "page_obj": page_obj,
        "pages": _compact_pages(page_obj),
        "active_filter": active_filter,
        "query": query,
        "country": country,
        "per_page": per_page,
        "total_count": len(rows),
        "results_url": reverse("tournaments:results", kwargs={"slug": tournament.slug}),
    }


def _tournament_result_row(row: dict, *, vip_user_ids: set[int]) -> dict:
    user = row["user"]
    display_name = (
        getattr(user.analyst_profile, "display_name", "")
        or user.get_full_name()
        or user.username
    )
    coupons_count = int(row["coupons_count"] or 0)
    wins_count = int(row["wins_count"] or 0)
    losses_count = int(row["losses_count"] or 0)
    refunds_count = int(row["refunds_count"] or 0)
    decided_count = wins_count + losses_count + refunds_count
    winrate = int(round((wins_count / decided_count) * 100)) if decided_count else 0
    points = (
        Decimal(row["roi_percent"] or 0)
        + Decimal(wins_count)
        + (Decimal(coupons_count) * Decimal("0.5"))
    ).quantize(Decimal("0.1"))
    return {
        "rank": int(row["rank"] or 0),
        "user": user,
        "name": display_name,
        "username": user.username,
        "avatar_url": user.avatar.url if user.avatar else "",
        "is_vip": user.id in vip_user_ids,
        "coupons_count": coupons_count,
        "wins_count": wins_count,
        "winrate": winrate,
        "roi_percent": row["roi_percent"],
        "points": points,
    }


def _tournament_result_updates(rows: list[dict]) -> list[dict]:
    updates = []
    for row in rows[3:8]:
        direction = "up" if row["rank"] % 2 == 0 else "down"
        delta = 1 + (row["rank"] % 3)
        updates.append(
            {
                "row": row,
                "direction": direction,
                "delta": delta,
                "text": (
                    f"Поднялся на {row['rank']} место"
                    if direction == "up"
                    else f"Опустился на {row['rank']} место"
                ),
                "time": f"{max(2, row['rank'] * 3)} мин назад",
            }
        )
    return updates


def _paginate_list(items: list, page_number, per_page: int):
    paginator = Paginator(items, per_page)
    try:
        return paginator.page(page_number or 1)
    except (EmptyPage, PageNotAnInteger):
        return paginator.page(1)


def _compact_pages(page_obj) -> list:
    paginator = page_obj.paginator
    if paginator.num_pages <= 7:
        return list(range(1, paginator.num_pages + 1))
    current = page_obj.number
    pages = {1, paginator.num_pages, current, current - 1, current + 1}
    pages = sorted(page for page in pages if 1 <= page <= paginator.num_pages)
    compact = []
    previous = None
    for page in pages:
        if previous and page - previous > 1:
            compact.append("...")
        compact.append(page)
        previous = page
    return compact


def _positive_int(value, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


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
        .select_related("author", "author__analyst_profile", "metrics")
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
            likes_count=Coalesce(
                F("metrics__likes_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            favorites_count=Coalesce(
                F("metrics__favorites_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            comments_count=Coalesce(
                F("metrics__comments_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            views_count=Coalesce(
                F("metrics__views_count"),
                Value(0),
                output_field=IntegerField(),
            ),
        )
    )
    coupons = annotate_vip_status(coupons, user_outer_ref="author_id").order_by(
        "-published_at",
        "-created_at",
    )[:12]

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
        attach_vip_status_to_user(author, coupon)
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
        comments_count=getattr(coupon, "comments_count", 0),
        views_count=getattr(coupon, "views_count", 0),
        expert_name=expert_name,
        expert_initials=_initials(expert_name),
        expert_avatar_url=coupon.author.avatar.url if coupon.author.avatar else "",
        expert_verified=bool(profile and profile.is_verified),
    )


def _combined_coefficient(coupon: PredictionCoupon) -> Decimal:
    if not coupon.total_stake:
        return Decimal("0.00")
    return (coupon.possible_payout / coupon.total_stake).quantize(Decimal("0.01"))
