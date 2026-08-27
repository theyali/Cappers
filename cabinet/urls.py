from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import avatar_views, dashboard_views, public_views, telegram_auth, views

app_name = "cabinet"

urlpatterns = [
    path("", dashboard_views.dashboard, name="dashboard"),
    path("reader/", views.legacy_reader_dashboard, name="reader_dashboard"),
    path("analyst/", views.legacy_analyst_dashboard, name="analyst_dashboard"),
    path("profile/", views.profile, name="profile"),
    path("coupons/<int:coupon_id>/", views.coupon_detail, name="coupon_detail"),
    path("profile/edit/", views.legacy_profile_edit, name="profile_edit"),
    path("profile/avatar/", avatar_views.avatar, name="avatar_upload"),
    path("profile/follow/<int:user_id>/", views.follow_analyst, name="follow_analyst"),
    path("experts/<str:username>/", public_views.expert_profile, name="expert_profile"),
    path("experts/<int:user_id>/follow/", public_views.toggle_follow, name="toggle_follow"),
    path("register/", views.register, name="register"),
    path(
        "login/",
        telegram_auth.TelegramAwareLoginView.as_view(),
        name="login",
    ),
    path("login/telegram/", telegram_auth.telegram_login, name="telegram_login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="cabinet/auth/password_reset_form.html",
            email_template_name="cabinet/auth/password_reset_email.txt",
            subject_template_name="cabinet/auth/password_reset_subject.txt",
            success_url=reverse_lazy("cabinet:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="cabinet/auth/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="cabinet/auth/password_reset_confirm.html",
            success_url=reverse_lazy("cabinet:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="cabinet/auth/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
