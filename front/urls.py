from django.urls import path

from cabinet import public_views as cabinet_public_views

from . import home_views, how_views, prediction_views, views

app_name = "front"

urlpatterns = [
    path("", home_views.index, name="index"),
    path("predictions/", prediction_views.predictions, name="predictions"),
    path(
        "predictions/<int:prediction_id>/like/",
        prediction_views.toggle_prediction_like,
        name="prediction_like",
    ),
    path(
        "predictions/<int:prediction_id>/favorite/",
        prediction_views.toggle_prediction_favorite,
        name="prediction_favorite",
    ),
    path("experts/<str:username>/", cabinet_public_views.expert_profile, name="expert_profile"),
    path("cappers/", views.cappers_stats, name="cappers_stats"),
    path("how-it-works/", how_views.how_it_works, name="how_it_works"),
]
