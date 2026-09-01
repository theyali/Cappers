from django.urls import path

from . import views


app_name = "wallets"

urlpatterns = [
    path("top-up/", views.top_up_balance, name="top_up"),
    path("real/action/", views.real_balance_action, name="real_action"),
    path("copybetting/<int:analyst_id>/", views.copybetting_setup, name="copybetting_setup"),
    path("copybetting/<int:subscription_id>/pause/", views.copybetting_pause, name="copybetting_pause"),
    path("copybetting/<int:subscription_id>/resume/", views.copybetting_resume, name="copybetting_resume"),
    path("copybetting/<int:subscription_id>/stop/", views.copybetting_stop, name="copybetting_stop"),
]
