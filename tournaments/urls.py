from django.urls import path

from . import views


app_name = "tournaments"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:slug>/predict/", views.predict, name="predict"),
    path("<slug:slug>/predict/matches/<int:match_id>/odds/", views.match_odds, name="match_odds"),
    path("<slug:slug>/join/", views.join, name="join"),
    path("<slug:slug>/coupon/create/", views.create_coupon, name="create_coupon"),
    path("<slug:slug>/", views.detail, name="detail"),
]
