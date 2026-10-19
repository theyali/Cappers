from django.urls import path

from . import views


app_name = "wallets"

urlpatterns = [
    path("top-up/", views.top_up_balance, name="top_up"),
    path("balance-visibility/", views.balance_visibility, name="balance_visibility"),
    path("real/action/", views.real_balance_action, name="real_action"),
    path("copybetting/search/", views.copybetting_search, name="copybetting_search"),
    path("copybetting/<int:analyst_id>/preview/", views.copybetting_preview, name="copybetting_preview"),
    path("copybetting/<int:analyst_id>/", views.copybetting_setup, name="copybetting_setup"),
    path("copybetting/<int:subscription_id>/pause/", views.copybetting_status, {"action": "pause"}, name="copybetting_pause"),
    path("copybetting/<int:subscription_id>/resume/", views.copybetting_status, {"action": "resume"}, name="copybetting_resume"),
    path("copybetting/<int:subscription_id>/stop/", views.copybetting_status, {"action": "stop"}, name="copybetting_stop"),
]
