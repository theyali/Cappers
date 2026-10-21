from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import date_format
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from cabinet.vip import active_vip_subscriptions, plural_ru
from game.models import Sport
from tournaments.models import (
    Tournament,
    TournamentAchievement,
    TournamentFAQ,
    TournamentParticipant,
    TournamentPrize,
    TournamentResult,
    TournamentStage,
)
from tournaments.services.eligibility import check_tournament_eligibility
from tournaments.services.join import TournamentJoinError, get_active_participant, join_tournament
from tournaments.services.leaderboard import tournament_leaderboard
from wallets.services import format_coins, format_money


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

    tournament_list = list(tournaments)
    participations_by_tournament = {}
    if request.user.is_authenticated and tournament_list:
        participations_by_tournament = {
            participation.tournament_id: participation
            for participation in TournamentParticipant.objects.filter(
                tournament_id__in=[item.pk for item in tournament_list],
                user=request.user,
                status=TournamentParticipant.Status.ACTIVE,
            ).select_related("result")
        }

    cards = [
        _tournament_card(
            tournament,
            now,
            participation=participations_by_tournament.get(tournament.pk),
        )
        for tournament in tournament_list
    ]
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
            "show_become_capper": request.user.is_authenticated and not request.user.is_analyst,
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


def _validation_message(exc: ValidationError) -> str:
    return exc.messages[0] if exc.messages else "Некорректные данные."


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


def _tournament_card(tournament: Tournament, now, *, participation=None) -> SimpleNamespace:
    allowed_sports = list(tournament.allowed_sports.all())
    is_all_sports = (
        not allowed_sports
        or "всем видам спорта" in tournament.title.casefold()
        or "все виды спорта" in tournament.title.casefold()
    )
    first_sport = allowed_sports[0] if len(allowed_sports) == 1 and not is_all_sports else None
    prizes = _active_prizes_by_place(tournament)
    prize_total = sum((prize.money_amount or Decimal("0") for prize in prizes), Decimal("0"))
    runtime_status = _runtime_status(tournament, now)
    if runtime_status["key"] == "finished":
        time_label = f"завершён {date_format(timezone.localtime(tournament.ends_at), 'j E')}"
    else:
        remaining = max(tournament.starts_at - now if runtime_status["key"] == "upcoming" else tournament.ends_at - now, timedelta(0))
        days = remaining.days
        hours = remaining.seconds // 3600
        if runtime_status["key"] == "upcoming":
            time_label = f"старт через {days} {plural_ru(days, 'день', 'дня', 'дней')}" if days else f"старт через {max(1, hours)} ч"
        else:
            time_label = f"{days} {plural_ru(days, 'день', 'дня', 'дней')} {hours} ч" if days else f"{hours} ч"

    rank = None
    if participation is not None:
        try:
            rank = participation.result.rank
        except TournamentResult.DoesNotExist:
            pass

    return SimpleNamespace(
        tournament=tournament,
        has_cover=bool(tournament.card_image or tournament.hero_image),
        status_label={"live": "Идёт сейчас", "upcoming": "Скоро старт", "finished": "Завершён"}[runtime_status["key"]],
        time_label=time_label,
        is_joined=participation is not None,
        participant_rank=rank,
        runtime_status=runtime_status,
        participants_count=getattr(tournament, "participants_count", 0),
        coupons_count=getattr(tournament, "coupons_count", 0),
        prize_total=prize_total,
        sport_code=(first_sport.code if first_sport else "all"),
        sport_label=(
            "Все виды спорта" if is_all_sports else
            (first_sport.name_ru or first_sport.name if first_sport else "Несколько видов спорта")
        ),
        sport_icon=_tournament_sport_icon(first_sport.code if first_sport else "all"),
    )


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
        f"Формат прогнозов: {tournament.get_prediction_format_display()}",
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
        getattr(getattr(user, "analyst_profile", None), "display_name", "")
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
