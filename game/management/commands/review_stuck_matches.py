from django.core.management.base import BaseCommand

from game.models import Match, MatchManualReview
from game.services.settlement import (
    flag_match_for_manual_review,
    get_match_score_review_reason,
)


class Command(BaseCommand):
    help = "Создать ручные проверки для завершённых матчей без валидного счёта."

    def handle(self, *args, **options):
        found = 0
        missing_score = 0
        invalid_score = 0

        matches = (
            Match.objects.filter(sync_scope=Match.SyncScope.FINISHED)
            .only("id", "score", "sync_scope")
            .order_by("id")
        )
        for match in matches.iterator(chunk_size=500):
            reason = get_match_score_review_reason(match)
            if reason is None:
                continue

            flag_match_for_manual_review(
                match,
                reason,
                {"score": match.score},
            )
            found += 1
            if reason == MatchManualReview.Reason.MISSING_SCORE:
                missing_score += 1
            elif reason == MatchManualReview.Reason.INVALID_SCORE:
                invalid_score += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Проверка завершена: "
                f"найдено {found}, "
                f"без счёта {missing_score}, "
                f"некорректный счёт {invalid_score}."
            )
        )
