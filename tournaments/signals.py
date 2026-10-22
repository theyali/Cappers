from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from game.models import PredictionCoupon
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant
from tournaments.services.leaderboard import invalidate_tournament_leaderboard
from tournaments.services.points import sync_participant_points


@receiver(post_save, sender=PredictionCoupon)
def sync_coupon_points(sender, instance, **kwargs):
    link = TournamentCoupon.objects.filter(coupon_id=instance.pk).first()
    if link:
        sync_participant_points(link.participant_id)
        invalidate_tournament_leaderboard(link.tournament_id)


@receiver(post_save, sender=TournamentCoupon)
@receiver(post_delete, sender=TournamentCoupon)
def sync_link_points(sender, instance, **kwargs):
    sync_participant_points(instance.participant_id)
    invalidate_tournament_leaderboard(instance.tournament_id)


@receiver(post_save, sender=TournamentParticipant)
@receiver(post_delete, sender=TournamentParticipant)
def sync_participant_status(sender, instance, **kwargs):
    sync_participant_points(instance.pk)
    invalidate_tournament_leaderboard(instance.tournament_id)


@receiver(post_save, sender=Tournament)
def invalidate_tournament_settings(sender, instance, **kwargs):
    invalidate_tournament_leaderboard(instance.pk)
