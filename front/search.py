"""Общие ограниченные выборки для поиска на главной и страницы результатов."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, F, Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystProfile
from game.models import Match, Prediction, PredictionCoupon
from tournaments.models import Tournament


SEARCH_GROUPS = (
    ("matches", "Матчи"),
    ("predictions", "Прогнозы"),
    ("cappers", "Капперы"),
    ("tournaments", "Турниры"),
)
SEARCH_SPORTS = (
    ("", "Все виды спорта"),
    ("football", "Футбол"),
    ("tennis", "Теннис"),
    ("basketball", "Баскетбол"),
    ("hockey", "Хоккей"),
)
SEARCH_DATES = (
    ("", "Любая дата"),
    ("today", "Сегодня"),
    ("tomorrow", "Завтра"),
    ("week", "7 дней"),
)
SEARCH_STATUSES = (
    ("", "Любой статус"),
    (PredictionCoupon.StateStatus.PENDING, "Ожидает"),
    (PredictionCoupon.StateStatus.WIN, "Выигрыш"),
    (PredictionCoupon.StateStatus.LOSE, "Проигрыш"),
)
SEARCH_COEFFICIENTS = (("", "Любой коэффициент"), ("1.5", "От 1,50"), ("2", "От 2,00"), ("3", "От 3,00"))
SPORT_ICONS = {"football": "⚽", "tennis": "🎾", "basketball": "🏀", "hockey": "🏒"}


def _match_name_filter(term):
    return (
        Q(home_team__name__icontains=term)
        | Q(home_team__name_ru__icontains=term)
        | Q(away_team__name__icontains=term)
        | Q(away_team__name_ru__icontains=term)
        | Q(league__name__icontains=term)
        | Q(league__name_ru__icontains=term)
    )


def _match_queryset(query):
    lookup = _match_name_filter(query)
    # Поиск полного названия пары должен находить матч, а не только отдельную команду.
    if " — " in query:
        home, away = (part.strip() for part in query.split(" — ", 1))
        if home and away:
            lookup |= (
                (Q(home_team__name__icontains=home) | Q(home_team__name_ru__icontains=home))
                & (Q(away_team__name__icontains=away) | Q(away_team__name_ru__icontains=away))
            )
    return (
        Match.objects.filter(lookup)
        .exclude(slug__isnull=True)
        .exclude(slug="")
    )


def _date_bounds(value):
    if value not in {"today", "tomorrow", "week"}:
        return None
    day = timezone.localdate() + timedelta(days=1 if value == "tomorrow" else 0)
    end = day + timedelta(days=7 if value == "week" else 1)
    return (
        timezone.make_aware(datetime.combine(day, time.min)),
        timezone.make_aware(datetime.combine(end, time.min)),
    )


def _format_date(value):
    return timezone.localtime(value).strftime("%d.%m · %H:%M") if value else "Дата не указана"


def build_search_context(query, *, preview=False, sport="", date="", status="", coefficient=""):
    query = (query or "").strip()[:100]
    filters = {
        "sport": sport if sport in dict(SEARCH_SPORTS) else "",
        "date": date if date in dict(SEARCH_DATES) else "",
        "status": status if status in dict(SEARCH_STATUSES) else "",
        "coefficient": coefficient if coefficient in dict(SEARCH_COEFFICIENTS) else "",
    }
    counts = {key: 0 for key, _ in SEARCH_GROUPS}
    rows = {key: [] for key, _ in SEARCH_GROUPS}
    if len(query) < 2:
        return {"query": query, "counts": counts, "total": 0, "groups": rows, "filters": filters}

    matches = _match_queryset(query)
    coupons = (
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
        )
        .filter(
            Q(headline__icontains=query)
            | Q(author__username__icontains=query)
            | Q(author__analyst_profile__display_name__icontains=query)
            | Q(predictions__match__in=matches.values("pk"))
        )
        .distinct()
    )
    cappers = AnalystProfile.objects.filter(is_public=True).filter(
        Q(display_name__icontains=query) | Q(user__username__icontains=query)
    )
    tournaments = Tournament.objects.filter(title__icontains=query)

    if filters["sport"]:
        matches = matches.filter(sport__code=filters["sport"])
        coupons = coupons.filter(predictions__match__sport__code=filters["sport"]).distinct()

    bounds = _date_bounds(filters["date"])
    if bounds:
        matches = matches.filter(starts_at__gte=bounds[0], starts_at__lt=bounds[1])
        coupons = coupons.filter(
            predictions__match__starts_at__gte=bounds[0],
            predictions__match__starts_at__lt=bounds[1],
        ).distinct()

    if filters["status"]:
        coupons = coupons.filter(state_status=filters["status"])
    if filters["coefficient"]:
        coupons = coupons.filter(
            total_stake__gt=0,
            possible_payout__gte=F("total_stake") * Decimal(filters["coefficient"]),
        )

    # Фильтры по ставкам и датам относятся к матчам/прогнозам, не к людям и турнирам.
    if any(filters.values()):
        cappers = cappers.none()
        tournaments = tournaments.none()
    if filters["status"] or filters["coefficient"]:
        matches = matches.none()

    counts["matches"] = matches.count()
    counts["predictions"] = coupons.count()
    counts["cappers"] = cappers.count()
    counts["tournaments"] = tournaments.count()
    limits = {"matches": 3 if preview else 8, "predictions": 0 if preview else 12,
              "cappers": 3 if preview else 8, "tournaments": 2 if preview else 6}

    if counts["matches"]:
        match_rows = (
            matches.select_related("home_team", "away_team", "league", "sport")
            .defer("raw_data", "winning_bet_keys", "refund_bet_keys", "odds_result_data", "provider_predictions")
            .annotate(
                prediction_count=Count(
                    "predictions__coupon",
                    filter=Q(
                        predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                        predictions__coupon__audience=PredictionCoupon.Audience.FREE,
                    ),
                    distinct=True,
                )
            )
            .order_by("-created_at", "-id")[:limits["matches"]]
        )
        for match in match_rows:
            rows["matches"].append({
                "title": f"{match.home_team_name} — {match.away_team_name}",
                "subtitle": f"{match.league_name or 'Матч'} · {_format_date(match.starts_at)}",
                "url": match.get_absolute_url(),
                "icon": SPORT_ICONS.get(match.sport_code, "🏆"),
                "count": match.prediction_count,
            })

    if limits["predictions"] and counts["predictions"]:
        positions = Prediction.objects.select_related(
            "match__home_team", "match__away_team", "match__league", "match__sport"
        ).defer(
            "match__raw_data", "match__winning_bet_keys", "match__refund_bet_keys",
            "match__odds_result_data", "match__provider_predictions",
        ).order_by("id")
        coupon_rows = (
            coupons.select_related("author", "author__analyst_profile")
            .prefetch_related(Prefetch("predictions", queryset=positions, to_attr="search_positions"))
            .order_by("-published_at", "-id")[:limits["predictions"]]
        )
        for coupon in coupon_rows:
            position = next(iter(coupon.search_positions), None)
            if not position:
                continue
            match = position.match
            profile = getattr(coupon.author, "analyst_profile", None)
            author = (profile.display_name if profile and profile.display_name
                      else coupon.author.get_full_name() or coupon.author.username)
            coefficient_value = (
                coupon.possible_payout / coupon.total_stake if coupon.total_stake else Decimal("0")
            )
            rows["predictions"].append({
                "title": f"{match.home_team_name} — {match.away_team_name}",
                "subtitle": f"{author} · {_format_date(match.starts_at)} · {position.selection}",
                "url": reverse("front:prediction_detail", args=(coupon.pk,)),
                "icon": SPORT_ICONS.get(match.sport_code, "🏆"),
                "coefficient": f"{coefficient_value:.2f}".replace(".", ","),
                "status": {
                    PredictionCoupon.StateStatus.PENDING: "Ожидает",
                    PredictionCoupon.StateStatus.WIN: "Выигрыш",
                    PredictionCoupon.StateStatus.LOSE: "Проигрыш",
                    PredictionCoupon.StateStatus.REFUND: "Возврат",
                }.get(coupon.state_status, coupon.get_state_status_display()),
                "status_key": coupon.state_status,
            })

    if counts["cappers"]:
        capper_rows = (
            cappers.select_related("user")
            .annotate(prediction_count=Count(
                "user__prediction_coupons",
                filter=Q(
                    user__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    user__prediction_coupons__audience=PredictionCoupon.Audience.FREE,
                ),
                distinct=True,
            ))
            .order_by("-prediction_count", "user__username")[:limits["cappers"]]
        )
        for profile in capper_rows:
            display_name = profile.display_name or profile.user.get_full_name() or profile.user.username
            rows["cappers"].append({
                "title": display_name,
                "subtitle": f"@{profile.user.username} · {profile.prediction_count} прогнозов",
                "url": reverse("front:expert_profile", args=(profile.user.username,)),
                "avatar": profile.user.avatar.url if profile.user.avatar else "",
                "initials": "".join(part[0] for part in display_name.split()[:2]).upper(),
                "rating": str(profile.trust_index) if profile.trust_index else "",
            })

    if counts["tournaments"]:
        tournament_rows = (
            tournaments.annotate(participant_count=Count("participants", distinct=True))
            .order_by("-starts_at", "-id")[:limits["tournaments"]]
        )
        for tournament in tournament_rows:
            rows["tournaments"].append({
                "title": tournament.title,
                "subtitle": f"{tournament.get_status_display()} · {tournament.participant_count} участников",
                "url": tournament.get_absolute_url(),
                "icon": "🏆",
            })

    return {
        "query": query,
        "counts": counts,
        "total": sum(counts.values()),
        "groups": rows,
        "filters": filters,
    }
