from dataclasses import dataclass
from typing import Callable

from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe

from .models import User


MAX_MOBILE_QUICK_ACCESS_ITEMS = 4
DEFAULT_MOBILE_QUICK_ACCESS = ("profile", "notifications", "predictions", "favorites")


@dataclass(frozen=True)
class MobileQuickAccessOption:
    key: str
    label: str
    icon_key: str
    icon_svg: str
    url_builder: Callable[[User], str]
    analyst_only: bool = False
    staff_only: bool = False


def _static_url(name: str) -> Callable[[User], str]:
    return lambda user: reverse(name)


def _profile_tab(tab: str) -> Callable[[User], str]:
    return lambda user: f"{reverse('cabinet:profile')}?tab={tab}"


def _public_profile(user: User) -> str:
    return reverse("front:expert_profile", kwargs={"username": user.username})


MOBILE_QUICK_ACCESS_OPTIONS = (
    MobileQuickAccessOption(
        "profile",
        "Профиль",
        "profile",
        '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"></circle><path d="M5 21a7 7 0 0 1 14 0"></path></svg>',
        _profile_tab("profile"),
    ),
    MobileQuickAccessOption(
        "notifications",
        "Уведомления",
        "bell",
        '<svg viewBox="0 0 24 24"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"></path><path d="M10 21h4"></path></svg>',
        _static_url("notifications:center"),
    ),
    MobileQuickAccessOption(
        "predictions",
        "Мои прогнозы",
        "chart",
        '<svg viewBox="0 0 24 24"><path d="M4 19V5"></path><path d="M8 19v-6"></path><path d="M13 19V9"></path><path d="M18 19V4"></path><path d="m7 11 5-5 3 3 5-5"></path></svg>',
        _profile_tab("predictions"),
        analyst_only=True,
    ),
    MobileQuickAccessOption(
        "favorites",
        "Избранное",
        "star",
        '<svg viewBox="0 0 24 24"><path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.8 1-6.1-4.4-4.3 6.1-.9L12 3Z"></path></svg>',
        _static_url("front:favorites"),
    ),
    MobileQuickAccessOption(
        "articles",
        "Статьи",
        "article",
        '<svg viewBox="0 0 24 24"><path d="M6 3.5h11a2 2 0 0 1 2 2v15H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z"></path><path d="M8 8h7M8 12h7M8 16h5"></path><path d="M19 6h1v14"></path></svg>',
        _static_url("front:articles"),
    ),
    MobileQuickAccessOption(
        "tournaments",
        "Турниры",
        "trophy",
        '<svg viewBox="0 0 24 24"><path d="M8 4h8v4a4 4 0 0 1-8 0V4Z"></path><path d="M8 6H4v2a4 4 0 0 0 4 4M16 6h4v2a4 4 0 0 1-4 4M12 12v4M8 21h8M9 16h6v5H9z"></path></svg>',
        _static_url("tournaments:index"),
    ),
    MobileQuickAccessOption(
        "how_it_works",
        "Как пользоваться",
        "book",
        '<svg viewBox="0 0 24 24"><path d="M4 5.5C6 4.5 8 4 10 4c1.2 0 2 .3 2 .3S12.8 4 14 4c2 0 4 .5 6 1.5v14c-2-1-4-1.5-6-1.5-1.2 0-2 .3-2 .3s-.8-.3-2-.3c-2 0-4 .5-6 1.5v-14Z"></path><path d="M12 4.3v14"></path></svg>',
        _static_url("front:how_it_works"),
    ),
    MobileQuickAccessOption(
        "achievements",
        "Достижения",
        "trophy",
        '<svg viewBox="0 0 24 24"><path d="M8 4h8v4a4 4 0 0 1-8 0V4Z"></path><path d="M8 6H4v2a4 4 0 0 0 4 4M16 6h4v2a4 4 0 0 1-4 4M12 12v4M8 21h8M9 16h6v5H9z"></path></svg>',
        _profile_tab("achievements"),
        analyst_only=True,
    ),
    MobileQuickAccessOption(
        "vip",
        "VIP",
        "star",
        '<svg viewBox="0 0 24 24"><path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.8 1-6.1-4.4-4.3 6.1-.9L12 3Z"></path></svg>',
        _static_url("cabinet:vip_plans"),
        analyst_only=True,
    ),
    MobileQuickAccessOption(
        "followers",
        "Подписчики",
        "profile",
        '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"></circle><path d="M3.5 19c.6-3.3 2.4-5 5.5-5s4.9 1.7 5.5 5M16 8h5M18.5 5.5v5"></path></svg>',
        _profile_tab("followers"),
        analyst_only=True,
    ),
    MobileQuickAccessOption(
        "earnings",
        "Доходы",
        "wallet",
        '<svg viewBox="0 0 24 24"><path d="M4 6h16v12H4zM8 10h8M8 14h5"></path><path d="M17 3v4M7 17v4"></path></svg>',
        _profile_tab("earnings"),
        analyst_only=True,
    ),
    MobileQuickAccessOption(
        "following",
        "Подписки",
        "profile",
        '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"></circle><path d="M3.5 19c.6-3.3 2.4-5 5.5-5s4.9 1.7 5.5 5M16 15l2 2 4-5"></path></svg>',
        _profile_tab("following"),
    ),
    MobileQuickAccessOption(
        "copybetting",
        "Копибеттинг",
        "chart",
        '<svg viewBox="0 0 24 24"><path d="M4 7h12M4 12h8M4 17h12M16 4l4 3-4 3M12 14l4 3-4 3"></path></svg>',
        _profile_tab("copybetting"),
    ),
    MobileQuickAccessOption(
        "wallet",
        "Баланс",
        "wallet",
        '<svg viewBox="0 0 24 24"><path d="M4 7.5h14a2 2 0 0 1 2 2v8.5H6a2 2 0 0 1-2-2V7.5Zm0 0V6a2 2 0 0 1 2-2h10M15 12h5"></path></svg>',
        _profile_tab("wallet"),
    ),
    MobileQuickAccessOption(
        "bonuses",
        "Мои бонусы",
        "gift",
        '<svg viewBox="0 0 24 24"><path d="M4 10h16v10H4zM3 7h18v4H3zM12 7v13"></path><path d="M12 7c-1.8 0-4.5-.7-4.5-2.6C7.5 3.1 8.5 2 9.8 2 11.7 2 12 4.7 12 7Zm0 0c1.8 0 4.5-.7 4.5-2.6C16.5 3.1 15.5 2 14.2 2 12.3 2 12 4.7 12 7Z"></path></svg>',
        _static_url("cabinet:bonuses"),
    ),
    MobileQuickAccessOption(
        "bonus_tasks",
        "Задания",
        "task",
        '<svg viewBox="0 0 24 24"><path d="M7 4h10M8 2h8v4H8zM5 5h14v16H5z"></path><path d="m8 11 2 2 4-4M8 17h8"></path></svg>',
        _static_url("cabinet:bonus_tasks"),
    ),
    MobileQuickAccessOption(
        "bonus_levels",
        "Уровни",
        "chart",
        '<svg viewBox="0 0 24 24"><path d="M4 19h16M6 16V9M12 16V5M18 16v-4"></path><path d="m5 7 5-4 4 3 5-4"></path></svg>',
        _static_url("cabinet:bonus_levels"),
    ),
    MobileQuickAccessOption(
        "referrals",
        "Рефералы",
        "profile",
        '<svg viewBox="0 0 24 24"><circle cx="8" cy="8" r="3"></circle><circle cx="17" cy="9" r="2.5"></circle><path d="M3 19c.6-3.4 2.4-5.1 5-5.1s4.4 1.7 5 5.1M14 14c3.3-.4 5.4 1.3 6 5"></path><path d="M16 4v4M14 6h4"></path></svg>',
        _static_url("cabinet:referrals"),
    ),
    MobileQuickAccessOption(
        "capper_articles",
        "Мои статьи",
        "article",
        '<svg viewBox="0 0 24 24"><path d="M5 4h10l4 4v12H5V4Z"></path><path d="M15 4v5h5M8 13h8M8 17h6"></path></svg>',
        _static_url("cabinet:capper_articles"),
        analyst_only=True,
    ),
    MobileQuickAccessOption(
        "public_profile",
        "Публичный профиль",
        "profile",
        '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"></circle><path d="M5.5 19.5c.8-3.6 3-5.4 6.5-5.4s5.7 1.8 6.5 5.4"></path></svg>',
        _public_profile,
        analyst_only=True,
    ),
    MobileQuickAccessOption(
        "settings",
        "Настройки",
        "settings",
        '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"></circle><path d="M19 12a7.2 7.2 0 0 0-.1-1l2-1.5-2-3.5-2.4 1a7.5 7.5 0 0 0-1.8-1L14.4 3h-4.8l-.3 3a7.5 7.5 0 0 0-1.8 1L5 6 3 9.5 5.1 11a7.2 7.2 0 0 0 0 2L3 14.5 5 18l2.5-1a7.5 7.5 0 0 0 1.8 1l.3 3h4.8l.3-3a7.5 7.5 0 0 0 1.8-1l2.5 1 2-3.5-2.1-1.5c.1-.3.1-.7.1-1Z"></path></svg>',
        _profile_tab("settings"),
    ),
    MobileQuickAccessOption(
        "bots",
        "Боты",
        "profile",
        '<svg viewBox="0 0 24 24"><circle cx="9" cy="9" r="3"></circle><circle cx="17" cy="8" r="2.5"></circle><path d="M3.5 19c.6-3.4 2.4-5.1 5.5-5.1s4.9 1.7 5.5 5.1M14 13.5c3.5-.4 5.7 1.3 6.5 5.5"></path></svg>',
        _static_url("bots:manage_accounts"),
        staff_only=True,
    ),
)


def available_mobile_quick_access_options(user: User) -> list[MobileQuickAccessOption]:
    result = []
    for option in MOBILE_QUICK_ACCESS_OPTIONS:
        if option.analyst_only and not user.is_analyst:
            continue
        if option.staff_only and not (user.is_staff or user.is_superuser):
            continue
        try:
            option.url_builder(user)
        except NoReverseMatch:
            continue
        result.append(option)
    return result


def normalized_mobile_quick_access_keys(user: User) -> list[str]:
    options = available_mobile_quick_access_options(user)
    allowed = {option.key for option in options}
    selected = [
        key
        for key in (user.mobile_quick_access or [])
        if isinstance(key, str) and key in allowed
    ]
    if not selected:
        selected = [key for key in DEFAULT_MOBILE_QUICK_ACCESS if key in allowed]

    for option in options:
        if len(selected) >= MAX_MOBILE_QUICK_ACCESS_ITEMS:
            break
        if option.key not in selected:
            selected.append(option.key)

    return selected[:MAX_MOBILE_QUICK_ACCESS_ITEMS]


def mobile_quick_access_items(user: User) -> list[dict]:
    options_by_key = {
        option.key: option
        for option in available_mobile_quick_access_options(user)
    }
    items = []
    for key in normalized_mobile_quick_access_keys(user):
        option = options_by_key.get(key)
        if option is None:
            continue
        items.append(
            {
                "key": option.key,
                "label": option.label,
                "url": option.url_builder(user),
                "icon_key": option.icon_key,
                "icon_svg": mark_safe(option.icon_svg),
            }
        )
    return items
