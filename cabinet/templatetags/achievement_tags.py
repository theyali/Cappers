from django import template

from achievements.evaluators import user_achievement_metrics
from cabinet.achievements import build_achievement_badges

register = template.Library()

RECENT_ACHIEVEMENTS_LIMIT = 4


@register.inclusion_tag("cabinet/_expert_achievements.html")
def expert_achievement_badges(
    expert,
    wins_count,
    overall_roi,
    followers_count,
    is_verified,
):
    metrics = user_achievement_metrics(
        expert,
        followers_count=followers_count,
        is_verified=is_verified,
    )
    all_badges = build_achievement_badges(
        predictions_count=metrics["predictions"],
        wins_count=wins_count,
        overall_roi=overall_roi,
        followers_count=metrics["followers"],
        best_win_streak=metrics["streak"],
        is_verified=bool(metrics["verified"]),
        likes_given=metrics["likes_given"],
        favorites_saved=metrics["favorites_saved"],
        referrals=metrics["referrals"],
    )
    badges = list(reversed(all_badges))[:RECENT_ACHIEVEMENTS_LIMIT]
    return {
        "achievement_badges": badges,
        "achievement_count": len(all_badges),
    }
