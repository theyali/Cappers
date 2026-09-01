from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cabinet.models import User
from tournaments.models import Tournament, TournamentParticipant


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
    if not user.is_analyst:
        raise TournamentJoinError("Участвовать в турнирах могут только капперы.")
    if tournament.status != Tournament.Status.PUBLISHED:
        raise TournamentJoinError("Турнир пока недоступен для подключения.")
    if timezone.now() > tournament.ends_at:
        raise TournamentJoinError("Турнир уже завершён.")

    with transaction.atomic():
        participant, created = TournamentParticipant.objects.select_for_update().get_or_create(
            tournament=tournament,
            user=user,
            defaults={"status": TournamentParticipant.Status.ACTIVE},
        )
        if participant.status == TournamentParticipant.Status.DISQUALIFIED:
            raise TournamentJoinError("Участник дисквалифицирован из этого турнира.")
        if not created and participant.status == TournamentParticipant.Status.LEFT:
            participant.status = TournamentParticipant.Status.ACTIVE
            participant.left_at = None
            participant.save(update_fields=("status", "left_at"))
        return participant


def leave_tournament(user: User, tournament: Tournament) -> TournamentParticipant:
    participant = get_active_participant(user, tournament)
    if participant is None:
        raise TournamentJoinError("Вы не участвуете в этом турнире.")
    participant.status = TournamentParticipant.Status.LEFT
    participant.left_at = timezone.now()
    participant.save(update_fields=("status", "left_at"))
    return participant
