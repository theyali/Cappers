from celery import shared_task
from django.core.cache import cache


# One rebuild at a time for every period: overlapping rebuilds ran the heavy
# ranking queries side by side and filled PostgreSQL's temporary files.
EXPERT_RANKING_REFRESH_LOCK_KEY = "expert-ranking:refresh:running"
EXPERT_RANKING_REFRESH_PENDING_KEY = "expert-ranking:refresh:pending"
EXPERT_RANKING_REFRESH_LOCK_SECONDS = 30 * 60
EXPERT_RANKING_REFRESH_MAX_PASSES = 3


@shared_task
def refresh_expert_rankings_task(periods=None):
    """Rebuild the ranking snapshots; a request made during a rebuild gets one more pass after it."""
    from .expert_ranking import refresh_core_expert_rankings

    pending = set(periods or ())
    try:
        lock_acquired = cache.add(
            EXPERT_RANKING_REFRESH_LOCK_KEY,
            True,
            timeout=EXPERT_RANKING_REFRESH_LOCK_SECONDS,
        )
    except Exception:
        lock_acquired = True
    if not lock_acquired:
        try:
            queued = set(cache.get(EXPERT_RANKING_REFRESH_PENDING_KEY) or ()) | pending
            cache.set(
                EXPERT_RANKING_REFRESH_PENDING_KEY,
                sorted(queued),
                timeout=EXPERT_RANKING_REFRESH_LOCK_SECONDS,
            )
        except Exception:
            pass
        return

    try:
        for _ in range(EXPERT_RANKING_REFRESH_MAX_PASSES):
            refresh_core_expert_rankings(periods=sorted(pending))
            try:
                queued = cache.get(EXPERT_RANKING_REFRESH_PENDING_KEY)
                cache.delete(EXPERT_RANKING_REFRESH_PENDING_KEY)
            except Exception:
                queued = None
            if queued is None:
                break
            pending = set(queued)
    finally:
        try:
            cache.delete(EXPERT_RANKING_REFRESH_LOCK_KEY)
        except Exception:
            pass
