from django.urls import path

from . import home_views, views

app_name = "front"

urlpatterns = [
    path("", home_views.index, name="index"),
    path("predictions/", views.predictions, name="predictions"),
    path("cappers/", views.cappers_stats, name="cappers_stats"),
]
