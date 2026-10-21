"""What a card shows, taken from a coupon or a capper profile, and the version that keys its cache.

Paid coupons follow the feed's rule for the public: teams, league and start time are shown, while
the pick, the odds and the money (which give the odds away) stay hidden, also after settlement.
"""

import hashlib
import re
from collections import Counter
from decimal import Decimal
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import Count, Max, Q, Subquery
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from cabinet.models import AnalystProfile, User
from cabinet.paid_predictions import get_active_paid_plans, profile_paid_subscriptions_enabled
from cabinet.vip import plural_ru
from front.capper_stats_service import CapperStatsService, _initials
from front.capper_table_service import MONTH_NAMES_GENITIVE
from front.expert_awards import leader_badges_for_users
from front.prediction_metrics import SETTLED_COUPON_STATES, author_roi_subquery
from front.sport_tabs import SPORT_TILE_KEYS
from game.models import Prediction, PredictionCoupon
from game.services.bet_options import compact_pick_label
from wallets.services import format_money

# Bump when the card design changes so that cached images are drawn again.
DESIGN_VERSION = 1
NEWBIE_SETTLED = 10
ROI_DAYS = 90
# The ROI note needs this many cappers with a ROI to compare with.
ROI_PEERS = 5
MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
PLAN_PERIODS = {1: "день", 7: "нед", 30: "мес"}
SCORE = re.compile(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$")
WINNER_PICK = re.compile(r"(^|· )([12])$")


def host() -> str:
    name = urlsplit(settings.SITE_BASE_URL).hostname or ""
    return name.removeprefix("www.")


def _version(*parts) -> str:
    raw = "|".join(str(part) for part in (DESIGN_VERSION, *parts))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _sport_key(code: str) -> str:
    return SPORT_TILE_KEYS.get((code or "").lower(), "x")


def _author(user, profile) -> dict:
    name = str(profile) if profile else user.get_full_name() or user.username
    trust = profile.trust_index if profile else Decimal("0")
    return {
        "name": name,
        "username": user.username,
        "verified": bool(profile and profile.is_verified),
        "trust": f"{trust:.1f}" if trust > 0 else "",
        "avatar": _avatar(user),
        "initials": _initials(name),
    }


def _avatar(user):
    if not user.avatar:
        return None
    try:
        with user.avatar.open("rb") as file:
            image = Image.open(file)
            image.draft("RGB", (256, 256))
            image.thumbnail((256, 256))
            return image.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


# Coupons -------------------------------------------------------------------------------------

def _when(starts_at) -> str:
    if not starts_at:
        return ""
    # Cards are shared by every viewer, so the project timezone, not the viewer's.
    local = timezone.localtime(starts_at, timezone.get_default_timezone())
    return f"{local.day} {MONTHS_SHORT[local.month - 1]}, {local:%H:%M}"


def _score(score: str) -> str:
    found = SCORE.match(score or "")
    return f"{found[1]} : {found[2]}" if found else (score or "")


def _pick(position) -> str:
    """The site's compact pick, with П1/П2 for the winner as in the mockup."""
    label = compact_pick_label(position)
    return WINNER_PICK.sub(r"\1П\2", label) if position.market in ("winner", "first_half_winner") else label


def _event(position, locked: bool) -> dict:
    match = position.match
    home = match.home_team_name or "Хозяева"
    away = match.away_team_name or "Гости"
    return {
        "title": f"{home} — {away}",
        "home": home,
        "away": away,
        "league": match.league_name,
        "when": _when(match.starts_at),
        "pick": "" if locked else _pick(position),
        "coefficient": "" if locked else f"{position.coefficient:.2f}",
        "sport": _sport_key(match.sport_code),
        "score": _score(match.score),
    }


def _paid_offer(coupon) -> tuple[str, str]:
    """Offer text and price for a locked coupon: the cheapest plan, else a single purchase."""
    author = coupon.author
    if profile_paid_subscriptions_enabled(author):
        plans = list(get_active_paid_plans(author))
        if not plans:
            return "Прогноз доступен по подписке", f"от {format_money(author.analyst_profile.paid_predictions_price)} ₽/мес"
        plan = min(plans, key=lambda item: item.price)
        period = PLAN_PERIODS.get(plan.duration_days)
        price = f"от {format_money(plan.price)} ₽/{period}" if period else f"от {format_money(plan.price)} ₽ за {plan.period_label}"
        return "Прогноз доступен по подписке", price
    if coupon.single_purchase_enabled and coupon.single_purchase_price:
        return "Прогноз доступен разово", f"{format_money(coupon.single_purchase_price)} ₽"
    return "Прогноз доступен подписчикам автора", ""


def coupon_card_data(coupon, positions: list) -> dict:
    """Card data for a published coupon; positions come with their matches loaded."""
    locked = coupon.audience == PredictionCoupon.Audience.PAID
    # A coupon whose events were removed still gets a card, named like its page.
    events = [_event(position, locked) for position in positions] or [{
        "title": f"Купон #{coupon.pk}", "home": "", "away": "", "league": "", "when": "",
        "pick": "", "coefficient": "", "sport": "x", "score": "",
    }]
    total = Decimal("1")
    for position in positions:
        total *= position.coefficient
    stake = coupon.total_stake or Decimal("0")
    amounts = {
        PredictionCoupon.StateStatus.WIN: f"+{format_money((coupon.possible_payout or 0) - stake)}",
        PredictionCoupon.StateStatus.LOSE: f"−{format_money(stake)}",
        PredictionCoupon.StateStatus.REFUND: format_money(stake),
    }
    sports = Counter(event["sport"] for event in events)
    data = {
        "state": coupon.state_status,
        "locked": locked,
        "sport": sports.most_common(1)[0][0],
        "author": _author(coupon.author, getattr(coupon.author, "analyst_profile", None)),
        "events": events,
        "coefficient": "" if locked or not positions else f"{total:.2f}",
        "stake": "" if locked else format_money(stake),
        "result_amount": "" if locked else amounts.get(coupon.state_status, ""),
        "host": host(),
    }
    if locked and coupon.state_status == PredictionCoupon.StateStatus.PENDING:
        data["offer"], data["price"] = _paid_offer(coupon)
    return data


def coupon_card_version(coupon) -> str:
    return _version("coupon", coupon.pk, coupon.updated_at.timestamp(), coupon.state_status, coupon.audience)


def coupon_card_url(request, coupon) -> str:
    path = reverse("front:og_coupon", args=[coupon.pk])
    return request.build_absolute_uri(f"{path}?v={coupon_card_version(coupon)}")


# Capper profiles -----------------------------------------------------------------------------

def _published(user):
    return PredictionCoupon.objects.filter(author=user, published_status=PredictionCoupon.PublishedStatus.PUBLISHED)


def _top_sports(user, profile) -> list[tuple[str, str]]:
    rows = (
        Prediction.objects.filter(
            coupon__author=user,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            match__sport__isnull=False,
        )
        .values("match__sport__code", "match__sport__name_ru", "match__sport__name")
        .annotate(total=Count("id"))
        .order_by("-total", "match__sport__code")[:2]
    )
    sports = [(row["match__sport__code"], row["match__sport__name_ru"] or row["match__sport__name"]) for row in rows]
    if sports:
        return sports
    return [("", name.strip()) for name in profile.favorite_sports.split(",") if name.strip()][:3]


def _leader_label(user) -> str:
    badges = leader_badges_for_users([user.pk]).get(user.pk, [])
    if not badges:
        return ""
    badge = badges[0]
    if badge["kind"] != "month":
        return badge["title"].upper()
    month = MONTH_NAMES_GENITIVE[badge["month"].month].upper()
    return f"ЛИДЕР РЕЙТИНГА {month}" if badge["rank"] == 1 else f"ТОП-{badge['rank']} РЕЙТИНГА {month}"


def _roi(user, days: int | None):
    """ROI in percent over settled coupons of the period, None when there are none."""
    return (
        User.objects.filter(pk=user.pk)
        .annotate(card_roi=Subquery(author_roi_subquery("pk", period_days=days)))
        .values_list("card_roi", flat=True)
        .first()
    )


def _roi_note(roi, days: int | None) -> str:
    peers = [
        value
        for value in AnalystProfile.objects.filter(is_public=True, user__role=User.Role.ANALYST)
        .annotate(card_roi=Subquery(author_roi_subquery("user_id", period_days=days)))
        .values_list("card_roi", flat=True)
        if value is not None
    ]
    others = len(peers) - 1
    if others < ROI_PEERS:
        return ""
    share = round(sum(1 for value in peers if value < roi) * 100 / others)
    if share >= 100:
        return "лучший ROI среди капперов"
    return f"выше, чем у {share}% капперов" if share >= 50 else ""


def _percent(value) -> str:
    text = f"{value:+.1f}%".replace(".", ",").replace("-", "−")
    return "0%" if value == 0 else text


def profile_card_data(profile) -> dict:
    from cabinet.expert_profile_views import _recent_performance

    user = profile.user
    published = _published(user)
    stats = published.aggregate(
        predictions=Count("id"),
        wins=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.WIN)),
        losses=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.LOSE)),
        settled=Count("id", filter=Q(state_status__in=SETTLED_COUPON_STATES)),
    )
    sports = _top_sports(user, profile)
    data = {
        "sport": _sport_key(sports[0][0]) if sports else "x",
        "author": _author(user, profile),
        "host": host(),
    }
    if stats["settled"] < NEWBIE_SETTLED:
        count = stats["predictions"]
        return {
            **data,
            "newbie": True,
            "predictions_label": f"{count} {plural_ru(count, 'прогноз', 'прогноза', 'прогнозов')}",
            "sport_names": [name for _code, name in sports],
        }

    days, roi_label = ROI_DAYS, "ROI ЗА 3 МЕСЯЦА"
    roi = _roi(user, days)
    if roi is None:
        days, roi_label = None, "ROI ЗА ВСЁ ВРЕМЯ"
        roi = _roi(user, None) or Decimal("0")
    decided = stats["wins"] + stats["losses"]
    streak = CapperStatsService._current_streak(published)
    win_streak = streak["state"] == PredictionCoupon.StateStatus.WIN and streak["count"] >= 2
    return {
        **data,
        "leader_label": _leader_label(user),
        "roi_label": roi_label,
        "roi": _percent(roi),
        "roi_note": _roi_note(roi, days) if roi > 0 else "",
        "hit_rate": f"{round(stats['wins'] * 100 / decided)}%" if decided else "—",
        "predictions": f"{stats['predictions']:,}".replace(",", " "),
        "streak": f"{streak['count']} подряд" if win_streak else "—",
        "streak_hot": win_streak and streak["count"] >= 3,
        "recent": list(_recent_performance(user, 10)["recent_states"]),
        "sports": " · ".join(name for _code, name in sports),
    }


def profile_card_version(profile) -> str:
    latest = _published(profile.user).aggregate(changed=Max("updated_at"), total=Count("id"))
    return _version(
        "capper", profile.user_id, profile.updated_at.timestamp(), profile.user.avatar.name if profile.user.avatar else "",
        latest["changed"], latest["total"], timezone.localdate(timezone=timezone.get_default_timezone()),
    )


def profile_card_url(request, profile) -> str:
    path = reverse("front:og_capper", args=[profile.user.username])
    return request.build_absolute_uri(f"{path}?v={profile_card_version(profile)}")
