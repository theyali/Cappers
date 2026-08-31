from django.contrib.auth import views as auth_views
from django.urls import path

from account_email import password_reset as password_reset_views

from . import (
    avatar_views,
    capper_views,
    dashboard_views,
    demand_views,
    referral_views,
    telegram_auth,
    user_public_views,
    views,
)

app_name = "cabinet"

urlpatterns = [
    path("", dashboard_views.dashboard, name="dashboard"),
    path("reader/", views.legacy_reader_dashboard, name="reader_dashboard"),
    path("analyst/", views.legacy_analyst_dashboard, name="analyst_dashboard"),
    path("profile/", views.profile, name="profile"),
    path("profile/achievements/", views.achievement_stats, name="achievement_stats"),
    path("profile/following/summary/", views.following_summary, name="following_summary"),
    path("referrals/stats/", referral_views.referral_stats, name="referral_stats"),
    path("prediction-demand/", demand_views.prediction_demand, name="prediction_demand"),
    path("coupons/<int:coupon_id>/", views.coupon_detail, name="coupon_detail"),
    path("profile/edit/", views.legacy_profile_edit, name="profile_edit"),
    path("profile/avatar/", avatar_views.avatar, name="avatar_upload"),
    path("profile/follow/<int:user_id>/", referral_views.follow_analyst, name="follow_analyst"),
    path(
        "experts/<int:user_id>/paid-subscribe/",
        views.subscribe_paid_predictions_view,
        name="paid_predictions_subscribe",
    ),
    path("users/<str:username>/", user_public_views.user_profile, name="user_profile"),
    path("experts/<int:user_id>/follow/", referral_views.toggle_follow, name="toggle_follow"),
    path("register/", capper_views.register, name="register"),
    path("become-capper/", capper_views.become_capper, name="become_capper"),
    path("become-capper/start/", capper_views.become_capper_start, name="become_capper_start"),
    path(
        "become-capper/onboarding/<int:step>/",
        capper_views.capper_onboarding,
        name="capper_onboarding",
    ),
    path(
        "login/",
        telegram_auth.TelegramAwareLoginView.as_view(),
        name="login",
    ),
    path("login/telegram/", telegram_auth.telegram_login, name="telegram_login"),
    path(
        "login/telegram-app/",
        telegram_auth.telegram_webapp_login,
        name="telegram_webapp_login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password-reset/",
        password_reset_views.AccountPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        password_reset_views.AccountPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        password_reset_views.consume_password_reset,
        name="password_reset_confirm",
    ),
    path(
        "reset/password/",
        password_reset_views.set_new_password,
        name="password_reset_set",
    ),
    path(
        "reset/complete/",
        password_reset_views.AccountPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
