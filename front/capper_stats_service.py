from datetime import timedelta

from django.utils import timezone

from cabinet.achievements import build_achievement_badges
from cabinet.models import AnalystFollow
from game.models import PredictionCoupon

from .expert_ranking import ranked_expert_profiles
from .prediction_metrics import ROI_PERIOD_DAYS


NEW_CAPPERS_LIMIT = 12
RISING_STARS_LIMIT = 12
POPULAR_CAPPERS_LIMIT = 12
ACTIVE_CAPPERS_LIMIT = 12
RISING_WINDOW_DAYS = 180
NEW_WINDOW_DAYS = 30


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _best_streaks_for_authors(author_ids: list[int]) -> dict[int, int]:
    if not author_ids:
        return {}

    rows = (
        PredictionCoupon.objects.filter(
            author_id__in=author_ids,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=[
                PredictionCoupon.StateStatus.WIN,
                PredictionCoupon.StateStatus.LOSE,
            ],
        )
        .order_by("author_id", "settled_at", "updated_at", "id")
        .values_list("author_id", "state_status")
    )

    best: dict[int, int] = {}
    current: dict[int, int] = {}
    for author_id, state in rows:
        if state == PredictionCoupon.StateStatus.WIN:
            current[author_id] = current.get(author_id, 0) + 1
            best[author_id] = max(best.get(author_id, 0), current[author_id])
        else:
            current[author_id] = 0
    return best


class CapperStatsService:
    """Single source of truth for capper catalog statistics and discovery.

    Ranking data, summary counters and newcomer discovery groups are assembled
    here so pages do not invent their own sorting or exposure rules.
    """

    def __init__(self, user=None):
        self.user = user

    def build_catalog_context(self) -> dict:
        profiles = ranked_expert_profiles()
        profile_ids = [profile.user_id for profile in profiles]
        best_streaks = _best_streaks_for_authors(profile_ids)
        following_ids = self._following_ids(profile_ids)

        cards_by_id = {
            profile.user_id: self._serialize_profile(
                profile,
                following_ids=following_ids,
                best_streak=best_streaks.get(profile.user_id, 0),
            )
            for profile in profiles
        }
        experts = [cards_by_id[profile.user_id] for profile in profiles]

        new_profiles = self._new_profiles(profiles)
        rising_profiles = self._rising_profiles(profiles)
        popular_profiles = self._popular_profiles(profiles)
        active_profiles = self._active_profiles(profiles)

        now = timezone.now()
        new_cutoff = now - timedelta(days=NEW_WINDOW_DAYS)
        summary = {
            "experts": len(profiles),
            "verified": sum(1 for profile in profiles if profile.is_verified),
            "publications": sum(profile.publications_count for profile in profiles),
            "active_30d": sum(
                1 for profile in profiles if profile.recent_publications_count > 0
            ),
            "new_30d": sum(
                1
                for profile in profiles
                if self._joined_at(profile) >= new_cutoff
            ),
            "rising": len(rising_profiles),
        }

        return {
            "experts": experts,
            "experts_count": len(experts),
            "summary": summary,
            "roi_period_days": ROI_PERIOD_DAYS,
            "new_cappers": [cards_by_id[profile.user_id] for profile in new_profiles],
            "rising_stars": [cards_by_id[profile.user_id] for profile in rising_profiles],
            "popular_cappers": [cards_by_id[profile.user_id] for profile in popular_profiles],
            "active_cappers": [cards_by_id[profile.user_id] for profile in active_profiles],
        }

    def _following_ids(self, profile_ids: list[int]) -> set[int]:
        if not getattr(self.user, "is_authenticated", False) or not profile_ids:
            return set()
        return set(
            AnalystFollow.objects.filter(
                follower=self.user,
                analyst_id__in=profile_ids,
            ).values_list("analyst_id", flat=True)
        )

    def _serialize_profile(
        self,
        profile,
        *,
        following_ids: set[int],
        best_streak: int,
    ) -> dict:
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        unlocked_achievements = build_achievement_badges(
            predictions_count=profile.publications_count,
            wins_count=profile.wins_count,
            overall_roi=profile.author_roi_all_time,
            followers_count=profile.followers_count,
            best_win_streak=best_streak,
            is_verified=profile.is_verified,
        )
        return {
            "id": profile.user_id,
            "name": name,
            "username": profile.user.username,
            "initials": _initials(name),
            "avatar_url": profile.avatar.url if profile.avatar else "",
            "verified": profile.is_verified,
            "roi": profile.author_roi,
            "roi_period_days": ROI_PERIOD_DAYS,
            "ranking_score": profile.ranking_score,
            "settled": profile.settled_count,
            "settled_in_roi_period": profile.roi_settled_count,
            "followers": profile.followers_count,
            "publications": profile.publications_count,
            "sports": profile.sports_count,
            "recent_publications": profile.recent_publications_count,
            "wins": profile.wins_count,
            "last_publication_at": profile.last_publication_at,
            "joined_at": self._joined_at(profile),
            "latest_achievements": list(reversed(unlocked_achievements[-5:])),
            "is_self": bool(
                getattr(self.user, "is_authenticated", False)
                and self.user.pk == profile.user_id
            ),
            "is_following": profile.user_id in following_ids,
        }

    @staticmethod
    def _joined_at(profile):
        return profile.onboarding_completed_at or profile.created_at

    def _new_profiles(self, profiles: list) -> list:
        completed = [profile for profile in profiles if profile.onboarding_completed_at]
        source = completed or profiles
        return sorted(
            source,
            key=lambda profile: (self._joined_at(profile), profile.user_id),
            reverse=True,
        )[:NEW_CAPPERS_LIMIT]

    def _rising_profiles(self, profiles: list) -> list:
        cutoff = timezone.now() - timedelta(days=RISING_WINDOW_DAYS)
        candidates = [
            profile
            for profile in profiles
            if profile.recent_publications_count > 0
            and (
                self._joined_at(profile) >= cutoff
                or profile.publications_count <= 25
            )
        ]
        candidates.sort(key=lambda profile: profile.user.username.lower())
        candidates.sort(
            key=lambda profile: (
                profile.recent_publications_count,
                profile.ranking_score,
                profile.wins_count,
                profile.followers_count,
                -profile.publications_count,
            ),
            reverse=True,
        )
        return candidates[:RISING_STARS_LIMIT]

    @staticmethod
    def _popular_profiles(profiles: list) -> list:
        return sorted(
            profiles,
            key=lambda profile: (
                profile.followers_count,
                profile.ranking_score,
                profile.publications_count,
            ),
            reverse=True,
        )[:POPULAR_CAPPERS_LIMIT]

    @staticmethod
    def _active_profiles(profiles: list) -> list:
        active = [profile for profile in profiles if profile.recent_publications_count > 0]
        active.sort(
            key=lambda profile: (
                profile.recent_publications_count,
                profile.last_publication_at or profile.created_at,
                profile.ranking_score,
            ),
            reverse=True,
        )
        return active[:ACTIVE_CAPPERS_LIMIT]
