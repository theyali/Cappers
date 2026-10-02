from django.utils import timezone

from .services.streaks import touch_daily_streak


DAILY_STREAK_SESSION_KEY = "daily_streak_seen_date"


class DailyVisitStreakMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._touch_daily_visit(request)
        return self.get_response(request)

    def _touch_daily_visit(self, request) -> None:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return

        today_key = timezone.localdate().isoformat()
        if request.session.get(DAILY_STREAK_SESSION_KEY) == today_key:
            return

        touch_daily_streak(user)
        request.session[DAILY_STREAK_SESSION_KEY] = today_key
