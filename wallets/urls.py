from django.urls import path

from . import views


app_name = "wallets"

urlpatterns = [
    path("top-up/", views.top_up_balance, name="top_up"),
]
