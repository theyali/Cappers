from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from game.models import PredictionCoupon
from wallets.services import ensure_capper_balance

from .capper_forms import (
    CapperAboutForm,
    CapperFocusForm,
    CapperIdentityForm,
    CapperSocialsForm,
)
from .forms import RegistrationForm
from .models import AnalystProfile, User


ACCOUNT_READER = "user"
ACCOUNT_CAPPER = "capper"
ACCOUNT_TYPES = {ACCOUNT_READER, ACCOUNT_CAPPER}
TOTAL_ONBOARDING_STEPS = 5


def _account_type_from_request(request) -> str:
    selected = (request.POST.get("account_type") or request.GET.get("type") or "").strip()
    if selected in ACCOUNT_TYPES:
        return selected
    posted_role = (request.POST.get("role") or "").strip()
    if posted_role == User.Role.ANALYST:
        return ACCOUNT_CAPPER
    if posted_role == User.Role.READER:
        return ACCOUNT_READER
    return ""


def _display_name_for(user: User) -> str:
    return user.get_full_name().strip() or user.telegram_username or user.username


def _profile_for_onboarding(user: User) -> AnalystProfile:
    profile, _ = AnalystProfile.objects.get_or_create(
        user=user,
        defaults={
            "display_name": _display_name_for(user),
            "telegram_account": f"@{user.telegram_username}" if user.telegram_username else "",
            "is_public": False,
        },
    )
    update_fields = []
    if not profile.display_name:
        profile.display_name = _display_name_for(user)
        update_fields.append("display_name")
    if not profile.telegram_account and user.telegram_username:
        profile.telegram_account = f"@{user.telegram_username}"
        update_fields.append("telegram_account")
    if user.role != User.Role.ANALYST and profile.is_public:
        profile.is_public = False
        update_fields.append("is_public")
    if update_fields:
        profile.save(update_fields=update_fields)
    return profile


def _first_incomplete_step(profile: AnalystProfile) -> int | None:
    """Return the first required onboarding step that still needs data.

    Photo, leagues and social networks are intentionally optional. A capper
    cannot activate a public profile without a public name, description,
    specialization and at least one sport focus.
    """
    if not (profile.display_name or "").strip():
        return 1
    if not (profile.specialization or "").strip() or not (profile.bio or "").strip():
        return 2
    if not (profile.favorite_sports or "").strip():
        return 3
    return None


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("cabinet:profile")

    selected_type = _account_type_from_request(request)
    form = None
    if selected_type:
        selected_role = (
            User.Role.ANALYST if selected_type == ACCOUNT_CAPPER else User.Role.READER
        )
        form = RegistrationForm(
            request.POST or None,
            initial={"role": selected_role},
        )

    if request.method == "POST":
        if selected_type not in ACCOUNT_TYPES:
            messages.error(request, "Сначала выберите тип аккаунта.")
            return redirect("cabinet:register")
        if form is not None and form.is_valid():
            wants_capper = selected_type == ACCOUNT_CAPPER
            with transaction.atomic():
                user = form.save(commit=False)
                # Каппер активируется только после onboarding, чтобы незаполненные
                # аккаунты не попадали в рейтинг и не публиковались случайно.
                user.role = User.Role.READER
                user.save()
                if wants_capper:
                    AnalystProfile.objects.create(
                        user=user,
                        display_name=_display_name_for(user),
                        is_public=False,
                    )
            login(request, user)
            if wants_capper:
                messages.success(request, "Аккаунт создан. Соберём ваш профиль каппера.")
                return redirect("cabinet:capper_onboarding", step=1)
            messages.success(request, "Регистрация завершена.")
            return redirect("cabinet:profile")

    return render(
        request,
        "cabinet/auth/register.html",
        {
            "form": form,
            "selected_type": selected_type,
            "selected_role": (
                User.Role.ANALYST
                if selected_type == ACCOUNT_CAPPER
                else User.Role.READER
            ),
        },
    )


def become_capper(request):
    profile = None
    if request.user.is_authenticated:
        profile = AnalystProfile.objects.filter(user=request.user).first()
    return render(
        request,
        "cabinet/capper/become_capper.html",
        {
            "capper_profile": profile,
            "already_capper": bool(
                request.user.is_authenticated and request.user.role == User.Role.ANALYST
            ),
        },
    )


@login_required
def become_capper_start(request):
    if request.user.role == User.Role.ANALYST:
        profile = AnalystProfile.objects.filter(user=request.user).first()
        if profile and profile.is_public:
            return redirect("front:expert_profile", username=request.user.username)

    _profile_for_onboarding(request.user)
    return redirect("cabinet:capper_onboarding", step=1)


@login_required
@require_http_methods(["GET", "POST"])
def capper_onboarding(request, step: int):
    if step < 1 or step > TOTAL_ONBOARDING_STEPS:
        return redirect("cabinet:capper_onboarding", step=1)

    profile = _profile_for_onboarding(request.user)
    if request.user.role == User.Role.ANALYST and profile.onboarding_completed_at and profile.is_public:
        return redirect("front:expert_profile", username=request.user.username)

    incomplete_step = _first_incomplete_step(profile)
    if incomplete_step is not None and step > incomplete_step:
        messages.info(request, "Сначала заполните обязательную часть профиля каппера.")
        return redirect("cabinet:capper_onboarding", step=incomplete_step)

    form = None
    step_title = ""
    step_copy = ""

    if step == 1:
        step_title = "Имя и фото"
        step_copy = "Соберите первое впечатление: это имя и фото будут видны в рейтинге и прогнозах."
        form = CapperIdentityForm(
            request.POST or None,
            request.FILES or None,
            initial={
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "display_name": profile.display_name or _display_name_for(request.user),
            },
        )
        if request.method == "POST" and form.is_valid():
            request.user.first_name = form.cleaned_data["first_name"].strip()
            request.user.last_name = form.cleaned_data["last_name"].strip()
            request.user.save(update_fields=["first_name", "last_name"])
            profile.display_name = form.cleaned_data["display_name"].strip()
            avatar = form.cleaned_data.get("avatar")
            if avatar:
                profile.avatar = avatar
            profile.save()
            return redirect("cabinet:capper_onboarding", step=2)

    elif step == 2:
        step_title = "Расскажите о себе"
        step_copy = "Покажите пользователям, почему стоит следить именно за вашей аналитикой."
        form = CapperAboutForm(
            request.POST or None,
            initial={
                "specialization": profile.specialization,
                "bio": profile.bio,
            },
        )
        if request.method == "POST" and form.is_valid():
            profile.specialization = form.cleaned_data["specialization"].strip()
            profile.bio = form.cleaned_data["bio"].strip()
            profile.save(update_fields=["specialization", "bio", "updated_at"])
            return redirect("cabinet:capper_onboarding", step=3)

    elif step == 3:
        step_title = "Спорт и лиги"
        step_copy = "Укажите, где вы сильнее всего. Это сразу объяснит аудитории вашу специализацию."
        form = CapperFocusForm(
            request.POST or None,
            initial={
                "favorite_sports": profile.favorite_sports,
                "favorite_leagues": profile.favorite_leagues,
            },
        )
        if request.method == "POST" and form.is_valid():
            profile.favorite_sports = form.cleaned_data["favorite_sports"].strip()
            profile.favorite_leagues = form.cleaned_data["favorite_leagues"].strip()
            profile.save(update_fields=["favorite_sports", "favorite_leagues", "updated_at"])
            return redirect("cabinet:capper_onboarding", step=4)

    elif step == 4:
        step_title = "Соцсети"
        step_copy = "Добавьте площадки, где аудитория уже вас знает. Telegram-вход мы подставим автоматически, если username доступен."
        form = CapperSocialsForm(
            request.POST or None,
            initial={
                "telegram_channel": profile.telegram_channel,
                "telegram_account": profile.telegram_account
                or (f"@{request.user.telegram_username}" if request.user.telegram_username else ""),
                "instagram": profile.instagram,
                "youtube": profile.youtube,
                "tiktok": profile.tiktok,
            },
        )
        if request.method == "POST" and form.is_valid():
            profile.telegram_channel = form.cleaned_data["telegram_channel"].strip()
            profile.telegram_account = form.cleaned_data["telegram_account"].strip()
            profile.instagram = form.cleaned_data["instagram"].strip()
            profile.youtube = form.cleaned_data["youtube"].strip()
            profile.tiktok = form.cleaned_data["tiktok"].strip()
            profile.save(
                update_fields=[
                    "telegram_channel",
                    "telegram_account",
                    "instagram",
                    "youtube",
                    "tiktok",
                    "updated_at",
                ]
            )
            return redirect("cabinet:capper_onboarding", step=5)

    else:
        step_title = "Профиль готов"
        step_copy = "Теперь можно открыть публичную страницу или сразу перейти к первому прогнозу."
        if request.method == "POST":
            incomplete_step = _first_incomplete_step(profile)
            if incomplete_step is not None:
                messages.error(request, "Заполните обязательные поля перед публикацией профиля.")
                return redirect("cabinet:capper_onboarding", step=incomplete_step)

            action = request.POST.get("action", "profile")
            with transaction.atomic():
                if request.user.role != User.Role.ANALYST:
                    request.user.role = User.Role.ANALYST
                    request.user.save(update_fields=["role"])
                ensure_capper_balance(request.user)
                profile.is_public = True
                if profile.onboarding_completed_at is None:
                    profile.onboarding_completed_at = timezone.now()
                profile.save(update_fields=["is_public", "onboarding_completed_at", "updated_at"])
            messages.success(
                request,
                "Профиль каппера активирован. Теперь ваша статистика будет собираться автоматически.",
            )
            if action == "prediction":
                match_list_url = reverse(
                    "game:match_list_filtered",
                    kwargs={
                        "sport": "all",
                        "scope": "prematch",
                        "selected_date": timezone.localdate().isoformat(),
                    },
                )
                return redirect(f"{match_list_url}?onboarding=done")
            return redirect("front:expert_profile", username=request.user.username)

    first_prediction_exists = PredictionCoupon.objects.filter(
        author=request.user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).exists()

    return render(
        request,
        "cabinet/capper/onboarding.html",
        {
            "form": form,
            "profile": profile,
            "step": step,
            "total_steps": TOTAL_ONBOARDING_STEPS,
            "step_title": step_title,
            "step_copy": step_copy,
            "previous_step": step - 1 if step > 1 else None,
            "next_step": step + 1 if step < TOTAL_ONBOARDING_STEPS else None,
            "progress_percent": round(step / TOTAL_ONBOARDING_STEPS * 100),
            "first_prediction_exists": first_prediction_exists,
        },
    )
