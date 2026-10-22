"""Presentation data for the participant directory in points and legacy ROI modes."""
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.urls import reverse
from django.utils import timezone

from game.models import PredictionCoupon
from tournaments.models import TournamentCoupon
from tournaments.services.leaderboard import has_tournament_result, tournament_leaderboard
from wallets.services import format_money


def build_tournament_participants_context(request, tournament, *, leaderboard=None):
    leaderboard = tournament_leaderboard(tournament) if leaderboard is None else leaderboard
    query = (request.GET.get("participants_q") or "").strip()[:150]
    order = "asc" if request.GET.get("participants_order") == "asc" else "desc"
    detail_url = tournament.get_absolute_url()

    def page_url(page=1, *, next_order=None):
        params = {"tab": "participants", "participants_page": page, "participants_order": next_order or order}
        if query:
            params["participants_q"] = query
        return f"{detail_url}?{urlencode(params)}"

    prizes = list(tournament.prizes.filter(is_active=True).select_related("achievement").order_by("place"))
    by_rank = {prize.place: prize for prize in prizes}
    rows = []
    own = None
    for source in leaderboard:
        user = source["user"]
        profile = getattr(user, "analyst_profile", None)
        name = getattr(profile, "display_name", "") or user.get_full_name() or user.username
        prize = by_rank.get(source["rank"]) if has_tournament_result(source) else None
        row = {
            "rank": source["rank"], "participant_id": source["participant"].pk,
            "name": name, "username": user.username,
            "profile_url": reverse("front:expert_profile", kwargs={"username": user.username}) if user.is_analyst
                else reverse("cabinet:user_profile", kwargs={"username": user.username}),
            "avatar_url": user.avatar.url if user.avatar else "", "is_verified": bool(getattr(profile, "is_verified", False)),
            "is_own": user.pk == request.user.pk,
            "coupons_count": source["coupons_count"], "wins_count": source["wins_count"],
            "points_label": source["score_label"], "points": source["points"],
            "base_points": source["base_points"], "bonus_points": source["bonus_points"],
            "has_result": has_tournament_result(source), "form": [],
            "money_label": format_money(prize.money_amount) if prize and prize.money_amount else "",
            "coins": prize.coins_amount if prize else 0,
            "prize_title": prize.title or (f"VIP на {prize.vip_days} дн." if prize.vip_days else "") if prize else "",
        }
        rows.append(row)
        if row["is_own"]:
            own = row
    total_coupons = sum(row["coupons_count"] for row in rows)
    filtered = [row for row in rows if not query or query.casefold() in row["name"].casefold()
                or query.casefold() in row["username"].casefold()]
    if order == "asc":
        filtered.reverse()
    page = Paginator(filtered, 10).get_page(request.GET.get("participants_page"))
    page_rows = list(page.object_list)
    # Five latest settled outcomes per visible participant, in one bounded query.
    form_rows = TournamentCoupon.objects.filter(
        tournament=tournament, participant_id__in=[row["participant_id"] for row in page_rows],
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        coupon__state_status__in=("win", "lose", "refund"),
    ).annotate(form_position=Window(expression=RowNumber(), partition_by=[F("participant_id")],
        order_by=[F("coupon__published_at").desc(nulls_last=True), F("id").desc()])
    ).filter(form_position__lte=5).order_by("participant_id", "-form_position").values_list(
        "participant_id", "coupon__state_status")
    forms = {}
    for participant_id, state in form_rows:
        forms.setdefault(participant_id, []).append({"state": state,
            "label": {"win": "Выигрыш", "lose": "Проигрыш", "refund": "Возврат"}[state]})
    for row in page_rows:
        row["form"] = forms.get(row["participant_id"], [])
    pages = [{"number": number, "url": page_url(number), "is_current": number == page.number}
             if isinstance(number, int) else {"ellipsis": True}
             for number in page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)]
    now = timezone.now()
    gap_label = "—"
    if own and tournament.uses_points and prizes:
        boundary = next((row for row in rows if row["rank"] == max(by_rank) and row["has_result"]), None)
        if not own["has_result"]:
            gap_label = "Нужен расчёт прогноза"
        elif own["rank"] in by_rank:
            gap_label = "В призовой зоне"
        elif boundary:
            gap = max(0, boundary["points"] - own["points"])
            gap_label = f"{gap} очков" if gap else "Равенство очков"
    return {
        "metric_label": "Очки" if tournament.uses_points else "ROI",
        "metric_unit": "очков" if tournament.uses_points else "ROI",
        "sort_label": "По очкам" if tournament.uses_points else "По ROI", "gap_label": gap_label,
        "rows": page_rows, "own": own, "query": query, "order": order,
        "page": page, "pages": pages, "total": len(rows), "filtered_total": len(filtered),
        "total_coupons": total_coupons, "prize_count": len(prizes),
        "prize_fund": format_money(sum(prize.money_amount for prize in prizes)),
        "sort_url": page_url(next_order="asc" if order == "desc" else "desc"),
        "next_url": page_url(page.next_page_number()) if page.has_next() else "",
        "endpoint": reverse("tournaments:participants", kwargs={"slug": tournament.slug}),
        "can_predict": bool(own and tournament.starts_at <= now <= tournament.ends_at),
        "prediction_url": reverse("game:match_list") + "?" + urlencode({"match_filter": "predictable", "tournament": tournament.pk}),
    }
