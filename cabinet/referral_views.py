from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .models import AnalystFollow, AnalystProfile, CapperReferralVisit, User
from .referrals import mark_referral_subscription, record_referral_visit


def _public_analyst_profile_by_handle(handle: str) -> AnalystProfile:
    value = (handle or "").strip().lstrip("@")
    profiles = AnalystProfile.objects.select_related("user").filter(
        user__role=User.Role.ANALYST,
        is_public=True,
    )

    profile = profiles.filter(user__username__iexact=value).first()
    if profile:
        return profile

    alternatives = list(
        profiles.filter(
            Q(display_name__iexact=value) | Q(user__telegram_username__iexact=value)
        )
        .distinct()[:2]
    )
    if len(alternatives) == 1:
        return alternatives[0]

    raise Http404("Каппер по этой реферальной ссылке не найден.")


@require_GET
def referral_redirect(request, username: str):
    """Compatibility route for old /r/<handle>/ links."""
    profile = _public_analyst_profile_by_handle(username)
    analyst = profile.user
    record_referral_visit(request, analyst)
    return redirect("front:expert_profile", username=analyst.username)


@require_GET
def referral_redirect_code(request, username: str, code: str):
    """Canonical referral route: /r/<username>/<random-code>/."""
    profile = get_object_or_404(
        AnalystProfile.objects.select_related("user"),
        referral_code__iexact=(code or "").strip(),
        user__role=User.Role.ANALYST,
        is_public=True,
    )
    analyst = profile.user

    if analyst.username.casefold() != (username or "").casefold():
        return redirect(
            "front:capper_referral_code",
            username=analyst.username,
            code=profile.referral_code,
            permanent=True,
        )

    record_referral_visit(request, analyst)
    return redirect("front:expert_profile", username=analyst.username)


@login_required
@require_POST
def toggle_follow(request, user_id: int):
    analyst = get_object_or_404(
        User,
        pk=user_id,
        role=User.Role.ANALYST,
        analyst_profile__is_public=True,
    )
    if analyst.pk == request.user.pk:
        return JsonResponse(
            {"ok": False, "error": "Нельзя подписаться на самого себя."},
            status=400,
        )

    follow, created = AnalystFollow.objects.get_or_create(
        follower=request.user,
        analyst=analyst,
    )
    active = created
    if created:
        mark_referral_subscription(request, analyst)
    else:
        follow.delete()
        active = False

    return JsonResponse(
        {
            "ok": True,
            "active": active,
            "followers_count": AnalystFollow.objects.filter(analyst=analyst).count(),
            "message": "Вы подписаны." if active else "Подписка отменена.",
        }
    )


@login_required
@require_POST
def follow_analyst(request, user_id: int):
    analyst = get_object_or_404(User, pk=user_id, role=User.Role.ANALYST)
    if analyst.pk == request.user.pk:
        return JsonResponse(
            {"ok": False, "error": "Нельзя подписаться на самого себя."},
            status=400,
        )

    _, created = AnalystFollow.objects.get_or_create(
        follower=request.user,
        analyst=analyst,
    )
    if created:
        mark_referral_subscription(request, analyst)
    return JsonResponse({"ok": True, "message": "Вы подписаны."})


@login_required
@require_GET
def referral_stats(request):
    if not request.user.is_analyst:
        return JsonResponse({"ok": False, "error": "Раздел доступен только капперам."}, status=403)

    profile = AnalystProfile.objects.filter(user=request.user).first()
    if not profile:
        return JsonResponse(
            {"ok": False, "error": "Профиль каппера не найден."},
            status=409,
        )

    visits = CapperReferralVisit.objects.filter(analyst=request.user)
    authenticated_visitors = (
        visits.filter(visitor__isnull=False)
        .values("visitor_id")
        .distinct()
        .count()
    )
    anonymous_visitors = visits.filter(visitor__isnull=True).count()
    visitors_count = authenticated_visitors + anonymous_visitors
    clicks_count = visits.aggregate(total=Sum("visits_count"))["total"] or 0
    subscriptions_count = (
        visits.filter(subscribed_at__isnull=False, visitor__isnull=False)
        .values("visitor_id")
        .distinct()
        .count()
    )
    conversion = round(subscriptions_count / visitors_count * 100, 1) if visitors_count else 0

    recent = []
    for visit in visits.select_related("visitor")[:40]:
        visitor = visit.visitor
        recent.append(
            {
                "username": visitor.username if visitor else "",
                "name": (
                    visitor.get_full_name().strip() or visitor.username
                    if visitor
                    else "Неавторизованный посетитель"
                ),
                "visits_count": visit.visits_count,
                "first_seen_at": visit.first_seen_at.isoformat(),
                "last_seen_at": visit.last_seen_at.isoformat(),
                "subscribed": visit.subscribed_at is not None,
                "subscribed_at": visit.subscribed_at.isoformat() if visit.subscribed_at else "",
            }
        )

    referral_url = request.build_absolute_uri(
        reverse(
            "front:capper_referral_code",
            kwargs={
                "username": request.user.username,
                "code": profile.referral_code,
            },
        )
    )
    return JsonResponse(
        {
            "ok": True,
            "referral_url": referral_url,
            "referral_code": profile.referral_code,
            "visitors_count": visitors_count,
            "clicks_count": clicks_count,
            "subscriptions_count": subscriptions_count,
            "conversion": conversion,
            "recent": recent,
        }
    )
