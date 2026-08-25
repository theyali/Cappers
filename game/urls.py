from django.urls import path

from . import views

app_name = "game"

urlpatterns = [
    path("", views.match_list, name="match_list"),
    path("coupon/create/", views.create_coupon, name="create_coupon"),
    path("<slug:slug>/", views.match_detail, name="match_detail"),
]
