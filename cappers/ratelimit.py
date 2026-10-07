from django.core.cache import cache


def limit_reached(key: str, *, limit: int) -> bool:
    return int(cache.get(f"ratelimit:{key}") or 0) >= limit


def count_attempt(key: str, *, window: int) -> int:
    """Count one attempt in a fixed window of ``window`` seconds; return the count."""
    cache_key = f"ratelimit:{key}"
    if cache.add(cache_key, 1, timeout=window):
        return 1
    try:
        return cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window)
        return 1


def rate_limited(key: str, *, limit: int, window: int) -> bool:
    """Count an attempt and report whether it goes over ``limit`` per window."""
    return count_attempt(key, window=window) > limit
