from django.urls import path

from . import date_views, prediction_views, views

app_name = "game"

urlpatterns = [
    path("", date_views.match_list, name="match_list"),
    path("coupon/create/", views.create_coupon, name="create_coupon"),
    path("<slug:slug>/predictions/", prediction_views.match_predictions, name="match_predictions"),
    path("<slug:slug>/", views.match_detail, name="match_detail"),
]
