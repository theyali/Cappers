from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import AnalystFollow, AnalystProfile, User
from .services import referral_bonuses
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
    return redirect("cabinet:register")


@require_GET
def referral_redirect_code(request, username: str, code: str):
    """Canonical referral route: /r/<username>/<random-code>/."""
    referrer = get_object_or_404(
        User,
        referral_code__iexact=(code or "").strip(),
    )

    if referrer.username.casefold() != (username or "").casefold():
        return redirect(
            "front:capper_referral_code",
            username=referrer.username,
            code=referrer.referral_code,
            permanent=True,
        )

    record_referral_visit(request, referrer)
    return redirect("cabinet:register")


@login_required
@require_POST
def toggle_follow(request, user_id: int):
    analyst = get_object_or_404(
        User.objects.select_related("analyst_profile"),
        pk=user_id,
        role=User.Role.ANALYST,
        analyst_profile__is_public=True,
    )
    if analyst.pk == request.user.pk:
        return JsonResponse(
            {"ok": False, "error": "Нельзя подписаться на самого себя."},
            status=400,
        )

    existing_follow = AnalystFollow.objects.filter(
        follower=request.user,
        analyst=analyst,
    ).first()
    if existing_follow is not None:
        existing_follow.delete()
        return JsonResponse(
            {
                "ok": True,
                "active": False,
                "followers_count": AnalystFollow.objects.filter(analyst=analyst).count(),
                "message": "Подписка отменена.",
            }
        )

    follow, created = AnalystFollow.objects.get_or_create(
        follower=request.user,
        analyst=analyst,
    )
    active = created
    if created:
        mark_referral_subscription(request, analyst)

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
    analyst = get_object_or_404(
        User.objects.select_related("analyst_profile"),
        pk=user_id,
        role=User.Role.ANALYST,
    )
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
def referrals(request):
    context = referral_bonuses.build_referrals_page_context(
        request.user,
        request=request,
    )
    context.update(
        {
            "active_tab": "referrals",
            "page_class": "cabinet-referrals-page",
        }
    )
    return render(request, "cabinet/referrals.html", context)


@login_required
@require_GET
def referral_stats(request):
    context = referral_bonuses.build_referrals_page_context(
        request.user,
        request=request,
    )
    return JsonResponse(
        {
            "ok": True,
            "referral_url": context["referral_url"],
            "referral_code": context["referral_code"],
            "can_earn_referrals": context["can_earn_referrals"],
            "referral_income_display": context["referral_income_display"],
            "visitors_count": context["visitors_count"],
            "clicks_count": context["clicks_count"],
            "registrations_count": context["registrations_count"],
            "subscriptions_count": context["subscriptions_count"],
            "conversion": context["conversion"],
            "bonus_settings": context["bonus_settings"],
            "bonus_cards": context["bonus_cards"],
            "recent": context["recent_visits"],
            "recent_visits": context["recent_visits"],
            "recent_bonus_events": context["recent_bonus_events"],
        }
    )
