from django.urls import path

from . import views

app_name = "game"

urlpatterns = [
    path("", views.match_list, name="match_list"),
]
