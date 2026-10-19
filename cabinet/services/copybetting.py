"""Read-only presentation of copybetting for analysts and readers."""
import csv
import io
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Q, Sum, Window
from django.db.models.functions import Coalesce, RowNumber
from django.urls import reverse
from django.utils import timezone

from game.models import PredictionCoupon
from wallets.models import CopiedBet, CopyBettingSubscription
from wallets.services import _copy_stake

PAGE_SIZE = 8
STATUS_LABELS = {"active": "Копирует", "paused": "На паузе", "stopped": "Остановил"}
RESULT_LABELS = {"pending": "Ждём", "win": "Прошла", "lose": "Не зашла", "refund": "Возврат"}


def coins(value, *, signed=False):
    amount = Decimal(value or 0)
    label = f"{amount:,.0f}".replace(",", " ")
    return f"+{label}" if signed and amount > 0 else label.replace("-", "−")


def audience_queryset(user, params):
    rows = CopyBettingSubscription.objects.filter(analyst=user)
    query = str(params.get("copy_q", "")).strip()[:100].lstrip("@")
    state = params.get("copy_status", "all")
    state = state if state in {"all", "active", "stopped"} else "all"
    period = params.get("copy_period", "all")
    period = period if period in {"all", "30", "7"} else "all"
    if query:
        rows = rows.filter(user__username__icontains=query)
    if state == "active":
        rows = rows.filter(status="active")
    elif state == "stopped":
        rows = rows.exclude(status="active")
    if period != "all":
        # The period describes the start date of the copying relationship.
        rows = rows.filter(started_at__gte=timezone.now() - timedelta(days=int(period)))
    person_id = str(params.get("copy_user", ""))
    valid_person = person_id.isascii() and person_id.isdigit() and len(person_id) <= 19
    valid_person = valid_person and 0 < int(person_id) <= 9223372036854775807
    if valid_person:
        rows = rows.filter(user_id=int(person_id))
    return rows, {"copy_q": query, "copy_status": state, "copy_period": period,
                  "copy_user": person_id if valid_person else ""}


def _person(subscription):
    person = subscription.user
    days = max(0, ((subscription.stopped_at or timezone.now()) - subscription.started_at).days)
    return {
        "id": person.pk, "username": person.username,
        "avatar": person.avatar.url if person.avatar else "", "initial": person.username[:1].upper(),
        "profile_url": reverse("cabinet:user_profile", args=[person.username]),
        "status": subscription.status, "status_label": STATUS_LABELS[subscription.status],
        "started_at": subscription.started_at, "stopped_at": subscription.stopped_at,
        "duration": f"{'Копировал' if subscription.status == 'stopped' else 'Копирует'} {days} дн.",
        "stake": coins(_copy_stake(subscription)),
        "profit": coins(subscription.total_profit, signed=True), "profit_positive": subscription.total_profit >= 0,
        "copied_count": subscription.copied_count, "total_staked": coins(subscription.total_staked),
    }


def build_copybetting_context(user, params):
    if not user.is_analyst:
        return build_reader_copybetting_context(user, params)
    base = CopyBettingSubscription.objects.filter(analyst=user)
    summary = base.aggregate(total=Count("pk"), active=Count("pk", filter=Q(status="active")), profit=Sum("total_profit"),
                             new=Count("pk", filter=Q(status="active", started_at__gte=timezone.now() - timedelta(days=7))))
    filtered, filters = audience_queryset(user, params)
    filtered = filtered.select_related("user").annotate(copied_count=Count("copied_bets"))
    page = Paginator(filtered.order_by("status", "-started_at", "-id"), PAGE_SIZE).get_page(params.get("copy_page", 1))
    people = [_person(row) for row in page.object_list]
    top = [_person(row) for row in base.select_related("user").annotate(copied_count=Count("copied_bets"))
           .order_by("-total_profit", "-id")[:3]]
    view = "bets" if params.get("copy_view") == "bets" else "audience"

    profile_url = reverse("cabinet:profile")
    def url(**changes):
        values = {"tab": "copybetting", **filters, "copy_view": view}
        values.update(changes)
        return f"{profile_url}?{urlencode({key: value for key, value in values.items() if value != ''})}"

    for person in people + top:
        person["bets_url"] = url(copy_view="bets", copy_user=person["id"], copy_page=1, copy_q="", copy_status="all", copy_period="all")
        person["stats_url"] = url(copy_view="audience", copy_user=person["id"], copy_page=1, copy_q="", copy_status="all", copy_period="all")
    selected = base.filter(user_id=filters["copy_user"]).select_related("user").annotate(copied_count=Count("copied_bets")).first() if filters["copy_user"] else None

    # Aggregate copies by source coupon; a coupon must appear once, not once per copier.
    bet_rows = CopiedBet.objects.filter(analyst=user)
    if filters["copy_user"]:
        bet_rows = bet_rows.filter(user_id=filters["copy_user"])
    if filters["copy_q"]:
        bet_rows = bet_rows.filter(user__username__icontains=filters["copy_q"])
    if filters["copy_period"] != "all":
        bet_rows = bet_rows.filter(created_at__gte=timezone.now() - timedelta(days=int(filters["copy_period"])))
    if filters["copy_status"] == "active":
        bet_rows = bet_rows.filter(subscription__status="active")
    elif filters["copy_status"] == "stopped":
        bet_rows = bet_rows.exclude(subscription__status="active")
    grouped = bet_rows.values("source_coupon_id").annotate(count=Count("user_id", distinct=True), amount=Sum("stake"), latest=Max("created_at")).order_by("-latest", "-source_coupon_id")
    bet_page = Paginator(grouped, PAGE_SIZE).get_page(params.get("copy_page", 1))
    groups = list(bet_page.object_list)
    coupon_ids = [row["source_coupon_id"] for row in groups]
    coupons = {c.pk: c for c in PredictionCoupon.objects.filter(pk__in=coupon_ids).prefetch_related("predictions__match__home_team", "predictions__match__away_team")}
    previews = {}
    if coupon_ids:
        copies = bet_rows.filter(source_coupon_id__in=coupon_ids).select_related("user").annotate(
            preview_row=Window(expression=RowNumber(), partition_by=[F("source_coupon_id")], order_by=F("id").asc()),
        ).filter(preview_row__lte=3).order_by("source_coupon_id", "id")
        for copy in copies:
            bucket = previews.setdefault(copy.source_coupon_id, [])
            if len(bucket) < 3:
                bucket.append({"username": copy.user.username, "avatar": copy.user.avatar.url if copy.user.avatar else "", "initial": copy.user.username[:1].upper()})
    bets = []
    for group in groups:
        coupon = coupons[group["source_coupon_id"]]
        positions = list(coupon.predictions.all())
        title = coupon.headline or f"Купон #{coupon.pk}"
        selection = ""
        if positions:
            match = positions[0].match
            if match.home_team and match.away_team:
                title = f"{match.home_team.name} — {match.away_team.name}"
            selection = positions[0].selection
            if len(positions) > 1:
                title = f"Экспресс · {len(positions)} игр"
                selection = f"{selection} и ещё {len(positions) - 1}"
        coefficient = coupon.possible_payout / coupon.total_stake if coupon.total_stake else 0
        bets.append({"id": coupon.pk, "url": reverse("front:prediction_detail", args=[coupon.pk]), "title": title,
                     "selection": selection, "coefficient": f"{coefficient:.2f}".replace(".", ","),
                     "count": group["count"], "extra": max(0, group["count"] - 3), "people": previews.get(coupon.pk, []),
                     "amount": coins(group["amount"]), "status": coupon.state_status, "result": RESULT_LABELS[coupon.state_status]})
    current = bet_page if view == "bets" else page
    public_url = reverse("front:expert_profile", args=[user.username])
    published = PredictionCoupon.objects.filter(author=user, published_status="published")
    progress = published.filter(state_status__in=["win", "lose", "refund"]).count()
    last = published.aggregate(latest=Max(Coalesce("published_at", "created_at")))["latest"]
    profile = user.analyst_profile
    regular = bool(last and last >= timezone.now() - timedelta(days=7))
    checklist = [
        {"label": "Публичный профиль", "complete": profile.is_public,
         "value": "открыт" if profile.is_public else "закрыт"},
        {"label": "Не меньше 20 рассчитанных прогнозов", "complete": progress >= 20,
         "value": f"{progress} из 20"},
        {"label": "Индекс доверия от 6.0", "complete": profile.trust_index >= Decimal("6.0"),
         "value": f"{profile.trust_index:.1f}"},
        {"label": "Публикации хотя бы раз в неделю", "complete": regular,
         "last_publication": last, "value": "публикаций пока нет"},
    ]
    return {
        "analyst_profile": profile,
        "copybetting_checklist": checklist,
        "copybetting_audience_active_count": summary["active"], "copybetting_audience_total_count": summary["total"],
        "copybetting_audience_profit": summary["profit"] or 0, "copybetting_audience_profit_display": coins(summary["profit"], signed=True),
        "copybetting_new_count": summary["new"], "copybetting_people": people, "copybetting_top": top,
        "copybetting_bets": bets, "copybetting_view": view, "copybetting_filters": filters,
        "copybetting_selected": _person(selected) if selected else None,
        "copybetting_filtered_count": current.paginator.count, "copybetting_start": current.start_index(),
        "copybetting_end": current.end_index(), "copybetting_has_more": current.has_next(),
        "copybetting_next_url": url(copy_page=current.next_page_number()) if current.has_next() else "",
        "copybetting_pages": [{"label": n, "url": url(copy_page=n), "active": n == current.number} if n != Paginator.ELLIPSIS else {"label": "…"}
                              for n in current.paginator.get_elided_page_range(current.number, on_each_side=1, on_ends=1)],
        "copybetting_audience_url": url(copy_view="audience", copy_page=1),
        "copybetting_bets_url": url(copy_view="bets", copy_page=1),
        "copybetting_reset_url": url(copy_view="audience", copy_user="", copy_q="", copy_status="all", copy_period="all", copy_page=1),
        "copybetting_export_url": reverse("cabinet:copybetting_audience") + "?" + urlencode({**filters, "export": "csv"}),
        "copybetting_share_path": public_url, "copybetting_settled_count": progress,
        "copybetting_last_publication": last, "copybetting_regular": bool(last and last >= timezone.now() - timedelta(days=7)),
    }


def build_audience_csv(user, params):
    rows, _ = audience_queryset(user, params)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Пользователь", "Начал", "Остановился", "Статус", "Сумма ставки, коины", "Результат, коины"])
    for row in rows.select_related("user").order_by("-started_at", "-id").iterator():
        name = row.user.username
        if name.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
            name = "'" + name
        writer.writerow([name, row.started_at.isoformat(), row.stopped_at.isoformat() if row.stopped_at else "",
                         row.get_status_display(), str(_copy_stake(row)), str(row.total_profit)])
    return "\ufeff" + output.getvalue()


def _sparkline(profits):
    values = [Decimal("0")]
    for profit in profits:
        values.append(values[-1] + profit)
    low, high = min(values), max(values)
    spread = high - low
    points = [f"{2 + i * 80 / max(1, len(values) - 1):.1f},{float(28 - (value - low) * 26 / spread) if spread else 15:.1f}"
              for i, value in enumerate(values)]
    if len(points) == 1:
        points.append("82.0,15.0")
    return " ".join(points)


def _copybetting_controls(subscription):
    pending = bool(subscription.pending_status)
    return {
        "can_pause": subscription.status == "active" and not pending,
        "can_resume": subscription.status == "paused" or (subscription.status == "active" and pending),
        "can_stop": subscription.status in {"active", "paused"},
        "stop_pending": subscription.pending_status == "stopped",
        "resume_label": "Продолжить" if pending else "Возобновить",
    }


def build_reader_copybetting_context(user, params):
    """The reader sees only their subscriptions and their own copied stakes."""
    base = CopyBettingSubscription.objects.filter(user=user)
    summary = base.aggregate(total=Count("pk"), active=Count("pk", filter=Q(status="active")),
                             paused=Count("pk", filter=Q(status="paused")), stopped=Count("pk", filter=Q(status="stopped")),
                             profit=Sum("total_profit"))
    query = str(params.get("copy_q", "")).strip().lstrip("@")[:100]
    state = params.get("copy_status", "all")
    state = state if state in {"all", "active", "paused", "stopped"} else "all"
    sort = params.get("copy_sort", "profit")
    sort = sort if sort in {"profit", "date"} else "profit"
    view = "bets" if params.get("copy_view") == "bets" else "following"
    filters = {"copy_q": query, "copy_status": state, "copy_sort": sort, "copy_view": view}
    def url(**changes):
        return reverse("cabinet:profile") + "?" + urlencode({"tab": "copybetting", **filters, **changes})
    following = base.select_related("analyst", "analyst__analyst_profile")
    if query:
        following = following.filter(Q(analyst__username__icontains=query) | Q(analyst__analyst_profile__display_name__icontains=query))
    if state != "all":
        following = following.filter(status=state)
    following = following.order_by("-total_profit" if sort == "profit" else "-started_at", "-id")
    page = Paginator(following, PAGE_SIZE).get_page(params.get("copy_page", 1))
    subscriptions = list(page.object_list)
    histories = {}
    if subscriptions:
        recent = CopiedBet.objects.filter(user=user, subscription_id__in=[s.pk for s in subscriptions]).exclude(state_status="pending").annotate(
            _reader_point=Window(expression=RowNumber(), partition_by=[F("subscription_id")], order_by=[F("settled_at").desc(nulls_last=True), F("id").desc()]),
        ).filter(_reader_point__lte=12).order_by("subscription_id", "-settled_at", "-id")
        for bet in recent:
            histories.setdefault(bet.subscription_id, []).append(bet.profit)
    rows = []
    for subscription in subscriptions:
        analyst = subscription.analyst
        profile = analyst.analyst_profile
        rows.append({
            "id": subscription.pk, "analyst_id": analyst.pk, "username": analyst.username,
            "name": profile.display_name or analyst.get_full_name() or analyst.username,
            "avatar": analyst.avatar.url if analyst.avatar else "", "initial": analyst.username[:1].upper(),
            "trust": profile.trust_index, "verified": profile.is_verified,
            "profile_url": reverse("front:expert_profile", args=[analyst.username]),
            "setup_url": reverse("wallets:copybetting_setup", args=[analyst.pk]),
            "bets_url": url(copy_view="bets", copy_q=analyst.username, copy_status="all", copy_page=1),
            "started_at": subscription.started_at, "status": subscription.status,
            "status_label": {"active": "Копирую", "paused": "На паузе", "stopped": "Остановлено"}[subscription.status],
            "pending_label": subscription.get_pending_status_display() if subscription.pending_status else "",
            **_copybetting_controls(subscription),
            "stake": coins(_copy_stake(subscription)), "profit": coins(subscription.total_profit, signed=True),
            "profit_positive": subscription.total_profit >= 0,
            "sparkline": _sparkline(reversed(histories.get(subscription.pk, []))),
            "sparkline_count": len(histories.get(subscription.pk, [])),
        })
    bets = CopiedBet.objects.filter(user=user, subscription__in=following.order_by().values("pk")).select_related("analyst", "analyst__analyst_profile")
    bet_page = Paginator(bets.order_by("-created_at", "-id"), PAGE_SIZE).get_page(params.get("copy_page", 1))
    copied = [{"id": bet.pk, "url": reverse("front:prediction_detail", args=[bet.source_coupon_id]),
               "title": f"Копия купона #{bet.source_coupon_id}", "analyst": bet.analyst.analyst_profile.display_name or bet.analyst.username,
               "created_at": bet.created_at, "stake": coins(bet.stake), "profit": coins(bet.profit, signed=True),
               "profit_positive": bet.profit >= 0, "status": bet.state_status, "result": RESULT_LABELS[bet.state_status]}
              for bet in bet_page.object_list] if view == "bets" else []
    current = bet_page if view == "bets" else page
    turnover = CopiedBet.objects.filter(user=user, created_at__gte=timezone.now() - timedelta(days=30)).aggregate(total=Sum("stake"))["total"]
    return {
        "copybetting_reader_rows": rows, "copybetting_reader_bets": copied,
        "copybetting_reader_active": summary["active"], "copybetting_reader_paused": summary["paused"],
        "copybetting_reader_turnover": coins(turnover), "copybetting_reader_profit": coins(summary["profit"], signed=True),
        "copybetting_reader_profit_positive": (summary["profit"] or 0) >= 0,
        "copybetting_reader_filters": filters,
        "copybetting_reader_statuses": [{"value": key, "label": label, "count": summary[key if key != "all" else "total"], "active": state == key}
                                        for key, label in [("all", "Все"), ("active", "Активные"), ("paused", "На паузе"), ("stopped", "Остановленные")]],
        "copybetting_reader_view": view, "copybetting_reader_following_url": url(copy_view="following", copy_page=1),
        "copybetting_reader_bets_url": url(copy_view="bets", copy_page=1),
        "copybetting_reader_reset_url": url(copy_q="", copy_status="all", copy_page=1),
        "copybetting_reader_return_url": url(copy_page=current.number),
        "copybetting_reader_total": current.paginator.count, "copybetting_reader_start": current.start_index(),
        "copybetting_reader_end": current.end_index(), "copybetting_reader_remaining": max(0, current.paginator.count - current.end_index()),
        "copybetting_reader_next_url": url(copy_page=current.next_page_number()) if current.has_next() else "",
        "copybetting_reader_previous_url": url(copy_page=current.previous_page_number()) if current.has_previous() else "",
        "copybetting_reader_has_more": current.has_next(),
    }


def build_public_copybetting_context(viewer, analyst):
    """Only the current reader's relationship and financial results are public-page context."""
    from cabinet.models import User

    visible = viewer.pk != analyst.pk and analyst.is_active and (not viewer.is_authenticated or viewer.role == User.Role.READER)
    if not visible:
        return {"public_copybetting": {"visible": False}}
    profile_url = reverse("front:expert_profile", args=[analyst.username])
    setup_url = reverse("wallets:copybetting_setup", args=[analyst.pk])
    data = {"visible": True, "status": "none", "hero_label": "Копировать", "hero_icon": "copy", "setup_url": setup_url,
            "return_url": profile_url, "hero_url": setup_url, "hero_mobile_url": setup_url}
    if not viewer.is_authenticated:
        from urllib.parse import quote
        data["setup_url"] = data["hero_url"] = data["hero_mobile_url"] = f"{reverse('cabinet:login')}?next={quote(setup_url)}"
        return {"public_copybetting": data}
    subscription = CopyBettingSubscription.objects.filter(user=viewer, analyst=analyst).first()
    if subscription:
        status = subscription.status
        profits = list(CopiedBet.objects.filter(user=viewer, subscription=subscription).exclude(state_status="pending")
                       .order_by("-settled_at", "-id").values_list("profit", flat=True)[:12])
        data.update(id=subscription.pk, status=status, started_at=subscription.started_at,
                    stopped_at=subscription.stopped_at, days=max(0, ((subscription.stopped_at or timezone.now()) - subscription.started_at).days),
                    stake=coins(_copy_stake(subscription)), profit=coins(subscription.total_profit, signed=True),
                    profit_positive=subscription.total_profit >= 0, sparkline=_sparkline(reversed(profits)), sparkline_count=len(profits),
                    hero_label={"active": "Копирую", "paused": "На паузе", "stopped": "Копировать"}[status],
                    hero_icon={"active": "check", "paused": "pause", "stopped": "copy"}[status],
                    pending_label=subscription.get_pending_status_display() if subscription.pending_status else "",
                    **_copybetting_controls(subscription),
                    hero_url="#expert-copybetting" if status in {"active", "paused"} else setup_url,
                    hero_mobile_url="#expert-copybetting-mobile" if status in {"active", "paused"} else setup_url,
                    bets_url=reverse("cabinet:profile") + "?" + urlencode({"tab": "copybetting", "copy_view": "bets", "copy_q": analyst.username}))
    return {"public_copybetting": data}
