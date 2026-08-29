from django.urls import path
from django.views.generic import TemplateView

from cabinet import expert_profile_views as cabinet_expert_profile_views
from cabinet import referral_views as cabinet_referral_views

from . import article_views, capper_views, feed_views, home_views, how_views, prediction_views, static_views

app_name = "front"

urlpatterns = [
    path("", home_views.index, name="index"),
    path(
        "r/<str:username>/<str:code>/",
        cabinet_referral_views.referral_redirect_code,
        name="capper_referral_code",
    ),
    path("r/<str:username>/", cabinet_referral_views.referral_redirect, name="capper_referral"),
    path("predictions/", prediction_views.predictions, name="predictions"),
    path(
        "predictions/<int:prediction_id>/",
        prediction_views.prediction_detail,
        name="prediction_detail",
    ),
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
    path(
        "predictions/<slug:sport_code>/",
        prediction_views.predictions,
        name="predictions_by_sport",
    ),
    path("feed/", feed_views.following_feed, name="following_feed"),
    path("favorites/", prediction_views.favorites, name="favorites"),
    path("articles/", article_views.articles, name="articles"),
    path("articles/<slug:slug>/", article_views.article_detail, name="article_detail"),
    path("experts/<str:username>/", cabinet_expert_profile_views.expert_profile, name="expert_profile"),
    path("cappers/", capper_views.cappers_stats, name="cappers_stats"),
    path("how-it-works/", how_views.how_it_works, name="how_it_works"),
    path(
        "rules/",
        TemplateView.as_view(template_name="front/rules.html"),
        name="rules",
    ),
    path("pages/<slug:slug>/", static_views.static_page, name="static_page"),
]
