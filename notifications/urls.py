from django.urls import path

from . import views, watch_views

app_name = "notifications"

urlpatterns = [
    path("", watch_views.center, name="center"),
    path("summary/", views.summary, name="summary"),
    path("preferences/", views.update_preferences, name="preferences"),
    path("telegram/connect/", views.telegram_connect, name="telegram_connect"),
    path("telegram/disconnect/", views.telegram_disconnect, name="telegram_disconnect"),
    path("read-all/", views.mark_all_read, name="mark_all_read"),
    path("<int:notification_id>/read/", views.mark_read, name="mark_read"),
    path("matches/<int:match_id>/watch/", watch_views.match_watch, name="match_watch"),
    path("matches/slug/<slug:match_slug>/watch/", watch_views.match_watch_by_slug, name="match_watch_by_slug"),
]
