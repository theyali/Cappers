from django import template

from cabinet.achievements import (
    ACHIEVEMENT_DEFINITIONS,
    _best_win_streak,
    _published_predictions_count,
    build_achievement_badges,
)

register = template.Library()


@register.inclusion_tag("cabinet/_expert_achievements.html")
def expert_achievement_badges(
    expert,
    wins_count,
    overall_roi,
    followers_count,
    is_verified,
):
    badges = build_achievement_badges(
        predictions_count=_published_predictions_count(expert),
        wins_count=wins_count,
        overall_roi=overall_roi,
        followers_count=followers_count,
        best_win_streak=_best_win_streak(expert),
        is_verified=is_verified,
    )
    return {
        "achievement_badges": badges,
        "achievement_count": len(badges),
    }
