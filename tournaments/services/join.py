from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cabinet.models import User
from tournaments.models import Tournament, TournamentParticipant
from tournaments.services.eligibility import check_tournament_eligibility
from wallets.models import CoinTransaction
from wallets.services import InsufficientCoins, charge_coins


class TournamentJoinError(ValidationError):
    pass


def get_active_participant(user: User, tournament: Tournament) -> TournamentParticipant | None:
    if not getattr(user, "is_authenticated", False):
        return None
    return TournamentParticipant.objects.filter(
        tournament=tournament,
        user=user,
        status=TournamentParticipant.Status.ACTIVE,
    ).first()


def join_tournament(user: User, tournament: Tournament) -> TournamentParticipant:
    if not getattr(user, "is_authenticated", False):
        raise TournamentJoinError("Войдите, чтобы подключиться к турниру.")
    if tournament.status != Tournament.Status.PUBLISHED:
        raise TournamentJoinError("Турнир пока недоступен для подключения.")
    now = timezone.now()
    if now > tournament.ends_at:
        raise TournamentJoinError("Турнир уже завершён.")
    active_participant = get_active_participant(user, tournament)
    if active_participant:
        return active_participant
    if now >= tournament.starts_at:
        raise TournamentJoinError("Регистрация на турнир завершена.")
    _validate_join_requirements(user, tournament)

    with transaction.atomic():
        participant = TournamentParticipant.objects.select_for_update().filter(
            tournament=tournament,
            user=user,
        ).first()
        if participant:
            if participant.status == TournamentParticipant.Status.DISQUALIFIED:
                raise TournamentJoinError("Участник дисквалифицирован из этого турнира.")
            if participant.status == TournamentParticipant.Status.ACTIVE:
                return participant

        _charge_entry_fee_if_needed(user, tournament)

        if participant:
            participant.status = TournamentParticipant.Status.ACTIVE
            participant.left_at = None
            participant.save(update_fields=("status", "left_at"))
            return participant

        return TournamentParticipant.objects.create(
            tournament=tournament,
            user=user,
            status=TournamentParticipant.Status.ACTIVE,
        )


def _validate_join_requirements(user: User, tournament: Tournament) -> None:
    eligibility = check_tournament_eligibility(user, tournament)
    if eligibility["allowed"]:
        return
    reasons = [reason for reason in eligibility["reasons"] if reason]
    raise TournamentJoinError(reasons[0] if reasons else "Вы не проходите условия участия в турнире.")


def _charge_entry_fee_if_needed(user: User, tournament: Tournament) -> None:
    if tournament.entry_type != Tournament.EntryType.PAID:
        return
    amount = int(tournament.entry_fee_coins or 0)
    if amount <= 0:
        raise TournamentJoinError("Для платного турнира не указана стоимость участия.")
    try:
        charge_coins(
            user,
            amount,
            CoinTransaction.Kind.TOURNAMENT_ENTRY_FEE,
            related_obj=tournament,
            note=f"Участие в турнире «{tournament.title}»",
        )
    except InsufficientCoins as exc:
        message = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
        raise TournamentJoinError(message) from exc


def leave_tournament(user: User, tournament: Tournament) -> TournamentParticipant:
    participant = get_active_participant(user, tournament)
    if participant is None:
        raise TournamentJoinError("Вы не участвуете в этом турнире.")
    participant.status = TournamentParticipant.Status.LEFT
    participant.left_at = timezone.now()
    participant.save(update_fields=("status", "left_at"))
    return participant
