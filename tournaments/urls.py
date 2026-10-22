from django.urls import path

from . import views


app_name = "tournaments"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:slug>/results/", views.results, name="results"),
    path("<slug:slug>/participants/", views.participants, name="participants"),
    path("<slug:slug>/join/", views.join, name="join"),
    path("<slug:slug>/", views.detail, name="detail"),
]
