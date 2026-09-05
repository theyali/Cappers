from django.urls import path

from . import views

app_name = "bots"

urlpatterns = [
    path("", views.manage_accounts, name="manage_accounts"),
]
