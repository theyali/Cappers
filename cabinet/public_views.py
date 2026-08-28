"""Compatibility exports for public expert actions.

Expert statistics are built by ``front.capper_stats_service.CapperStatsService``
and rendered through ``expert_profile_views``. Keep these imports so older code
that imports ``cabinet.public_views`` continues to work without maintaining a
second copy of the statistics logic.
"""

from .expert_profile_views import expert_profile
from .referral_views import toggle_follow

__all__ = ["expert_profile", "toggle_follow"]
