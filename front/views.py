from django.db.models import Count
from django.shortcuts import render

from cabinet.models import AnalystProfile, User


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
