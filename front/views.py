from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import render
from django.utils import timezone

from cabinet.models import AnalystProfile, User
from game.models import Prediction, PredictionCoupon


LATEST_PREDICTIONS = [
    {
        "sport": "Футбол",
        "league": "Премьер-лига",
        "match": "Арсенал — Ливерпуль",
        "pick": "Тотал больше 2.5",
        "coefficient": "1.82",
        "confidence": 78,
        "starts_at": "Сегодня, 21:45",
        "expert": "Макс Орлов",
        "expert_initials": "МО",
        "note": "Обе команды держат высокий темп и регулярно создают моменты после перерыва.",
    },
    {
        "sport": "Теннис",
        "league": "ATP",
        "match": "Синнер — Медведев",
        "pick": "Победа Синнера",
        "coefficient": "1.64",
        "confidence": 84,
        "starts_at": "Сегодня, 19:30",
        "expert": "Антон Белый",
        "expert_initials": "АБ",
        "note": "По текущей форме и качеству первой подачи преимущество остается на стороне фаворита.",
    },
    {
        "sport": "Баскетбол",
        "league": "Евролига",
        "match": "Фенербахче — Олимпиакос",
        "pick": "Фора хозяев -3.5",
        "coefficient": "1.91",
        "confidence": 73,
        "starts_at": "Завтра, 20:00",
        "expert": "Роман Ким",
        "expert_initials": "РК",
        "note": "Домашняя площадка и более глубокая ротация дают хозяевам запас по концовке матча.",
    },
    {
        "sport": "Хоккей",
        "league": "КХЛ",
        "match": "Ак Барс — СКА",
        "pick": "Обе забьют: да",
        "coefficient": "1.58",
        "confidence": 81,
        "starts_at": "Завтра, 18:30",
        "expert": "Илья Север",
        "expert_initials": "ИС",
        "note": "Команды стабильно создают давление в большинстве, а в очных матчах редко уходят без шайбы.",
    },
    {
        "sport": "Киберспорт",
        "league": "CS2",
        "match": "Spirit — Vitality",
        "pick": "Тотал карт больше 2.5",
        "coefficient": "2.05",
        "confidence": 76,
        "starts_at": "Пт, 22:00",
        "expert": "Данил Рэй",
        "expert_initials": "ДР",
        "note": "Пулы карт пересекаются так, что у обеих команд есть комфортный пик и высокий шанс на решающую карту.",
    },
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
    (Prediction.StateStatus.WIN, "Выиграли"),
    (Prediction.StateStatus.LOSE, "Проиграли"),
    (Prediction.StateStatus.REFUND, "Возврат"),
)


def _initials(name: str) -> str:
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _top_experts():
    profiles = list(
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        )
        .select_related("user")
        .annotate(followers_count=Count("user__analyst_followers"))
        .order_by("-followers_count", "-is_verified", "-created_at")[:5]
    )

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
    context = {
        "latest_predictions": LATEST_PREDICTIONS,
        "top_experts": _top_experts(),
    }
    return render(request, "front/index.html", context)


def predictions(request):
    active_status = request.GET.get("status", "all")
    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    published = Prediction.objects.filter(
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    counts = published.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(state_status="") | Q(state_status__isnull=True)),
        win=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
        lose=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
        refund=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
    )

    queryset = published.select_related(
        "coupon__author",
        "coupon__author__analyst_profile",
        "match__league",
        "match__home_team",
        "match__away_team",
    )
    if active_status == "pending":
        queryset = queryset.filter(Q(state_status="") | Q(state_status__isnull=True))
    elif active_status != "all":
        queryset = queryset.filter(state_status=active_status)

    paginator = Paginator(
        queryset.order_by("-coupon__published_at", "-coupon__created_at", "-created_at"),
        24,
    )
    page_obj = paginator.get_page(request.GET.get("page"))

    for prediction in page_obj.object_list:
        author = prediction.coupon.author
        profile = getattr(author, "analyst_profile", None)
        name = (
            profile.display_name
            if profile and profile.display_name
            else author.get_full_name() or author.username
        )
        prediction.expert_name = name
        prediction.expert_initials = _initials(name)
        prediction.expert_avatar_url = profile.avatar.url if profile and profile.avatar else ""
        prediction.expert_verified = bool(profile and profile.is_verified)

    count_map = {
        "all": counts["total"],
        "pending": counts["pending"],
        Prediction.StateStatus.WIN: counts["win"],
        Prediction.StateStatus.LOSE: counts["lose"],
        Prediction.StateStatus.REFUND: counts["refund"],
    }
    status_tabs = [
        {
            "key": key,
            "label": label,
            "count": count_map.get(key, 0),
        }
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


def cappers_stats(request):
    recent_cutoff = timezone.now() - timedelta(days=30)
    published_filter = Q(
        user__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED
    )

    profiles = list(
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        )
        .select_related("user")
        .annotate(
            followers_count=Count("user__analyst_followers", distinct=True),
            publications_count=Count(
                "user__prediction_coupons__predictions",
                filter=published_filter,
                distinct=True,
            ),
            sports_count=Count(
                "user__prediction_coupons__predictions__match__sport",
                filter=published_filter,
                distinct=True,
            ),
            recent_publications_count=Count(
                "user__prediction_coupons__predictions",
                filter=published_filter
                & Q(user__prediction_coupons__published_at__gte=recent_cutoff),
                distinct=True,
            ),
            last_publication_at=Max(
                "user__prediction_coupons__published_at",
                filter=published_filter,
            ),
        )
        .order_by(
            "-recent_publications_count",
            "-publications_count",
            "-followers_count",
            "-is_verified",
            "-created_at",
        )
    )

    experts = []
    for profile in profiles:
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        experts.append(
            {
                "name": name,
                "username": profile.user.username,
                "initials": _initials(name),
                "avatar_url": profile.avatar.url if profile.avatar else "",
                "verified": profile.is_verified,
                "followers": profile.followers_count,
                "publications": profile.publications_count,
                "sports": profile.sports_count,
                "recent_publications": profile.recent_publications_count,
                "last_publication_at": profile.last_publication_at,
                "joined_at": profile.created_at,
            }
        )

    summary = {
        "experts": len(profiles),
        "verified": sum(1 for profile in profiles if profile.is_verified),
        "publications": sum(profile.publications_count for profile in profiles),
        "active_30d": sum(1 for profile in profiles if profile.recent_publications_count > 0),
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
