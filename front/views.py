from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render

from cabinet.achievements import build_achievement_badges
from cabinet.models import AnalystFollow
from game.models import PredictionCoupon

from .expert_ranking import ranked_expert_profiles


LATEST_PREDICTIONS = [
    {"sport": "Футбол", "league": "Премьер-лига", "match": "Арсенал — Ливерпуль", "pick": "Тотал больше 2.5", "coefficient": "1.82", "confidence": 78, "starts_at": "Сегодня, 21:45", "expert": "Макс Орлов", "expert_initials": "МО", "note": ""},
    {"sport": "Теннис", "league": "ATP", "match": "Синнер — Медведев", "pick": "Победа Синнера", "coefficient": "1.64", "confidence": 84, "starts_at": "Сегодня, 19:30", "expert": "Антон Белый", "expert_initials": "АБ", "note": ""},
    {"sport": "Баскетбол", "league": "Евролига", "match": "Фенербахче — Олимпиакос", "pick": "Фора хозяев -3.5", "coefficient": "1.91", "confidence": 73, "starts_at": "Завтра, 20:00", "expert": "Роман Ким", "expert_initials": "РК", "note": ""},
    {"sport": "Хоккей", "league": "КХЛ", "match": "Ак Барс — СКА", "pick": "Обе забьют: да", "coefficient": "1.58", "confidence": 81, "starts_at": "Завтра, 18:30", "expert": "Илья Север", "expert_initials": "ИС", "note": ""},
    {"sport": "Киберспорт", "league": "CS2", "match": "Spirit — Vitality", "pick": "Тотал карт больше 2.5", "coefficient": "2.05", "confidence": 76, "starts_at": "Пт, 22:00", "expert": "Данил Рэй", "expert_initials": "ДР", "note": ""},
]


DEMO_EXPERTS = [
    {"name": "Макс Орлов", "username": "maxbet", "followers": 2840, "initials": "МО", "verified": True},
    {"name": "Антон Белый", "username": "whitepick", "followers": 2190, "initials": "АБ", "verified": True},
    {"name": "Роман Ким", "username": "rk.analytics", "followers": 1780, "initials": "РК", "verified": False},
    {"name": "Илья Север", "username": "northline", "followers": 1460, "initials": "ИС", "verified": True},
    {"name": "Данил Рэй", "username": "raytips", "followers": 1190, "initials": "ДР", "verified": False},
]


PREDICTION_STATUS_FILTERS = (
    ("all", "Все"),
    ("pending", "Ожидают"),
    (PredictionCoupon.StateStatus.WIN, "Выиграли"),
    (PredictionCoupon.StateStatus.LOSE, "Проиграли"),
    (PredictionCoupon.StateStatus.REFUND, "Возврат"),
)


def _initials(name: str) -> str:
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _top_experts():
    profiles = ranked_expert_profiles(limit=5)
    if not profiles:
        return DEMO_EXPERTS

    experts = []
    for profile in profiles:
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        experts.append(
            {
                "name": name,
                "username": profile.user.username,
                "followers": profile.followers_count,
                "initials": _initials(name),
                "verified": profile.is_verified,
                "avatar_url": profile.avatar.url if profile.avatar else "",
            }
        )
    return experts


def index(request):
    return render(
        request,
        "front/index.html",
        {"latest_predictions": LATEST_PREDICTIONS, "top_experts": _top_experts()},
    )


def predictions(request):
    active_status = request.GET.get("status", "all")
    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    published = PredictionCoupon.objects.filter(
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED
    )
    counts = published.aggregate(
        total=Count("id"),
        pending=Count(
            "id", filter=Q(state_status=PredictionCoupon.StateStatus.PENDING)
        ),
        win=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.WIN)),
        lose=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.LOSE)),
        refund=Count(
            "id", filter=Q(state_status=PredictionCoupon.StateStatus.REFUND)
        ),
    )

    queryset = published.select_related("author", "author__analyst_profile")
    if active_status == "pending":
        queryset = queryset.filter(state_status=PredictionCoupon.StateStatus.PENDING)
    elif active_status != "all":
        queryset = queryset.filter(state_status=active_status)

    paginator = Paginator(queryset.order_by("-published_at", "-created_at"), 24)
    page_obj = paginator.get_page(request.GET.get("page"))

    count_map = {
        "all": counts["total"],
        "pending": counts["pending"],
        PredictionCoupon.StateStatus.WIN: counts["win"],
        PredictionCoupon.StateStatus.LOSE: counts["lose"],
        PredictionCoupon.StateStatus.REFUND: counts["refund"],
    }
    status_tabs = [
        {"key": key, "label": label, "count": count_map.get(key, 0)}
        for key, label in PREDICTION_STATUS_FILTERS
    ]

    return render(
        request,
        "front/predictions.html",
        {
            "page_obj": page_obj,
            "status_tabs": status_tabs,
            "active_status": active_status,
            "total_predictions": counts["total"],
        },
    )


def _best_streaks_for_authors(author_ids: list[int]) -> dict[int, int]:
    if not author_ids:
        return {}

    rows = (
        PredictionCoupon.objects.filter(
            author_id__in=author_ids,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=[
                PredictionCoupon.StateStatus.WIN,
                PredictionCoupon.StateStatus.LOSE,
            ],
        )
        .order_by("author_id", "settled_at", "updated_at", "id")
        .values_list("author_id", "state_status")
    )

    best: dict[int, int] = {}
    current: dict[int, int] = {}
    for author_id, state in rows:
        if state == PredictionCoupon.StateStatus.WIN:
            current[author_id] = current.get(author_id, 0) + 1
            best[author_id] = max(best.get(author_id, 0), current[author_id])
        else:
            current[author_id] = 0
    return best


def cappers_stats(request):
    profiles = ranked_expert_profiles()

    following_ids = set()
    if request.user.is_authenticated:
        following_ids = set(
            AnalystFollow.objects.filter(follower=request.user).values_list(
                "analyst_id", flat=True
            )
        )

    best_streaks = _best_streaks_for_authors([profile.user_id for profile in profiles])
    experts = []
    for profile in profiles:
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        unlocked_achievements = build_achievement_badges(
            predictions_count=profile.publications_count,
            wins_count=profile.wins_count,
            overall_roi=profile.author_roi,
            followers_count=profile.followers_count,
            best_win_streak=best_streaks.get(profile.user_id, 0),
            is_verified=profile.is_verified,
        )
        experts.append(
            {
                "id": profile.user_id,
                "name": name,
                "username": profile.user.username,
                "initials": _initials(name),
                "avatar_url": profile.avatar.url if profile.avatar else "",
                "verified": profile.is_verified,
                "roi": profile.author_roi,
                "ranking_score": profile.ranking_score,
                "settled": profile.settled_count,
                "followers": profile.followers_count,
                "publications": profile.publications_count,
                "sports": profile.sports_count,
                "recent_publications": profile.recent_publications_count,
                "last_publication_at": profile.last_publication_at,
                "joined_at": profile.created_at,
                "latest_achievements": list(reversed(unlocked_achievements[-5:])),
                "is_self": request.user.is_authenticated
                and request.user.pk == profile.user_id,
                "is_following": profile.user_id in following_ids,
            }
        )

    summary = {
        "experts": len(profiles),
        "verified": sum(1 for profile in profiles if profile.is_verified),
        "publications": sum(profile.publications_count for profile in profiles),
        "active_30d": sum(
            1 for profile in profiles if profile.recent_publications_count > 0
        ),
    }
    return render(
        request,
        "front/cappers_stats.html",
        {
            "experts": experts,
            "experts_count": len(experts),
            "summary": summary,
        },
    )
