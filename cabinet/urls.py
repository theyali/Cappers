from django.contrib.auth import views as auth_views
from django.urls import path, re_path

from account_email import password_reset as password_reset_views

from . import (
    avatar_views,
    bonus_views,
    capper_views,
    dashboard_views,
    demand_views,
    earnings_views,
    profile_promo_views,
    referral_views,
    telegram_auth,
    user_public_views,
    views,
    vip_views,
)
from .roulette import api as roulette_api

app_name = "cabinet"

urlpatterns = [
    path("", dashboard_views.dashboard, name="dashboard"),
    path("reader/", views.legacy_reader_dashboard, name="reader_dashboard"),
    path("analyst/", views.legacy_analyst_dashboard, name="analyst_dashboard"),
    path("profile/", views.profile, name="profile"),
    path("articles/", views.capper_articles, name="capper_articles"),
    path("articles/new/", views.capper_article_create, name="capper_article_create"),
    path(
        "articles/<int:article_id>/edit/",
        views.capper_article_edit,
        name="capper_article_edit",
    ),
    path(
        "articles/<int:article_id>/submit/",
        views.capper_article_submit,
        name="capper_article_submit",
    ),
    path(
        "profile/promo-banner/",
        profile_promo_views.profile_promo_banner,
        name="profile_promo_banner",
    ),
    path("vip/purchase/", vip_views.vip_purchase, name="vip_purchase"),
    path("bonuses/", bonus_views.bonuses, name="bonuses"),
    path("bonuses/tasks/", bonus_views.daily_tasks, name="bonus_tasks"),
    path("bonuses/levels/", bonus_views.bonus_levels, name="bonus_levels"),
    path("referrals/", referral_views.referrals, name="referrals"),
    path(
        "bonuses/daily-tasks/<int:task_id>/claim/",
        bonus_views.daily_task_claim,
        name="daily_task_claim",
    ),
    path("bonuses/roulette/state/", roulette_api.roulette_state, name="roulette_state"),
    path("bonuses/roulette/spin/", roulette_api.roulette_spin, name="roulette_spin"),
    path("profile/request-verification/", views.request_verification, name="request_verification"),
    path("profile/delete-account/", views.delete_account, name="delete_account"),
    path("profile/earnings/", earnings_views.profile_earnings, name="profile_earnings"),
    path("profile/achievements/", views.achievement_stats, name="achievement_stats"),
    path("profile/following/summary/", views.following_summary, name="following_summary"),
    path("referrals/stats/", referral_views.referral_stats, name="referral_stats"),
    path("prediction-demand/", demand_views.prediction_demand, name="prediction_demand"),
    path("coupons/<int:coupon_id>/", views.coupon_detail, name="coupon_detail"),
    path("profile/edit/", views.legacy_profile_edit, name="profile_edit"),
    path("profile/avatar/", avatar_views.avatar, name="avatar_upload"),
    path("profile/cover/", avatar_views.cover, name="cover_upload"),
    path("profile/follow/<int:user_id>/", referral_views.follow_analyst, name="follow_analyst"),
    path(
        "experts/<int:user_id>/paid-subscribe/",
        views.subscribe_paid_predictions_view,
        name="paid_predictions_subscribe",
    ),
    path(
        "experts/<int:user_id>/paid-decline/",
        views.decline_paid_predictions_view,
        name="paid_predictions_decline",
    ),
    path("users/<str:username>/", user_public_views.user_profile, name="user_profile"),
    path("experts/<int:user_id>/follow/", referral_views.toggle_follow, name="toggle_follow"),
    path("register/", capper_views.register, name="register"),
    path("league-search/", capper_views.league_search, name="league_search"),
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
    re_path(
        r"^reset/(?P<uidb64>[^/]+)/(?P<token>[^/]+)/(?P<trailing>[\u200b\u200c\u200d\u2060\ufeff]+)/?$",
        password_reset_views.consume_password_reset,
        name="password_reset_confirm_invisible_suffix",
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
