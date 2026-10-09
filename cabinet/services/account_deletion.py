from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from account_email.models import EmailChangeRequest, EmailVerificationRequest, PasswordResetRequest
from cabinet.models import AnalystFollow, AnalystPaidSubscription, AnalystProfile, User
from notifications.models import NotificationPreference, TelegramAccount, TelegramLinkToken
from wallets.models import CapperRealBalance, CopyBettingSubscription
from wallets.services import format_money


DELETED_DISPLAY_NAME = "Удалённый пользователь"


def account_deletion_blockers(user) -> list[str]:
    """Reasons the account cannot be deleted yet: money that still belongs to the user."""
    reasons = []
    balance = CapperRealBalance.objects.filter(user=user).first()
    if balance is not None:
        if balance.balance > 0:
            reasons.append(f"На реальном балансе {format_money(balance.balance)} ₽: сначала выведите их.")
        if balance.pending_withdrawal > 0:
            reasons.append("Заявка на вывод ещё не обработана.")
        if balance.held > 0:
            reasons.append(f"Доход {format_money(balance.held)} ₽ ещё в холде.")
    if AnalystPaidSubscription.objects.filter(analyst=user, expires_at__gt=timezone.now()).exists():
        reasons.append("У вас есть активные платные подписчики: дождитесь окончания их подписок.")
    return reasons


@transaction.atomic
def delete_user_account(user) -> User:
    """Delete an account without losing financial records.

    Financial history (coin and real-money transactions, payments, copied bets)
    stays for accounting, linked to an anonymous inactive user. Personal data is
    wiped and the account can no longer sign in.
    """
    user = User.objects.select_for_update().get(pk=user.pk)
    CapperRealBalance.objects.select_for_update().filter(user=user).first()
    reasons = account_deletion_blockers(user)
    if reasons:
        raise ValidationError(reasons)

    now = timezone.now()
    if user.avatar:
        user.avatar.delete(save=False)
    user.username = f"deleted-{user.pk}"
    user.first_name = ""
    user.last_name = ""
    user.email = ""
    user.email_verified = False
    user.telegram_id = None
    user.telegram_username = ""
    user.registration_ip = None
    user.mobile_quick_access = []
    user.is_active = False
    user.deleted_at = now
    user.set_unusable_password()
    user.save()

    profile = AnalystProfile.objects.filter(user=user).first()
    if profile is not None:
        for field in (
            "bio",
            "specialization",
            "telegram_channel",
            "telegram_account",
            "instagram",
            "threads",
            "youtube",
            "tiktok",
            "facebook",
            "x",
        ):
            setattr(profile, field, "")
        profile.display_name = DELETED_DISPLAY_NAME
        profile.is_public = False
        profile.paid_predictions_enabled = False
        profile.save()

    NotificationPreference.objects.filter(user=user).update(
        email_enabled=False,
        telegram_enabled=False,
        telegram_chat_id="",
        telegram_username="",
        telegram_connected_at=None,
    )
    TelegramAccount.objects.filter(user=user).delete()
    TelegramLinkToken.objects.filter(user=user).delete()
    EmailVerificationRequest.objects.filter(user=user).delete()
    EmailChangeRequest.objects.filter(user=user).delete()
    PasswordResetRequest.objects.filter(user=user).delete()
    for follow in AnalystFollow.objects.filter(Q(follower=user) | Q(analyst=user)):
        follow.delete()
    # Copies already placed still settle; nothing new is copied to or from the account.
    CopyBettingSubscription.objects.filter(Q(user=user) | Q(analyst=user)).exclude(
        status=CopyBettingSubscription.Status.STOPPED,
    ).update(
        status=CopyBettingSubscription.Status.STOPPED,
        pending_status="",
        pending_status_requested_at=None,
        stopped_at=now,
    )
    return user
