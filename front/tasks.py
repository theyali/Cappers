from celery import shared_task
from django.core.cache import cache


EXPERT_RANKING_REFRESH_LOCK_SECONDS = 300


def _ranking_refresh_lock_key(periods: list[str]) -> str:
    value = ",".join(periods) if periods else "core"
    return f"expert-ranking:refresh:running:{value}"


@shared_task
def refresh_expert_rankings_task(periods=None):
    from .expert_ranking import refresh_core_expert_rankings

    period_list = list(periods or ())
    lock_key = _ranking_refresh_lock_key(period_list)
    lock_acquired = False
    try:
        lock_acquired = cache.add(
            lock_key,
            True,
            timeout=EXPERT_RANKING_REFRESH_LOCK_SECONDS,
        )
    except Exception:
        lock_acquired = True
    if not lock_acquired:
        return

    try:
        refresh_core_expert_rankings(periods=period_list)
    finally:
        try:
            cache.delete(lock_key)
        except Exception:
            pass
