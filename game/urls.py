from django.urls import path

from . import (
    date_views,
    demand_views,
    match_detail_views,
    prediction_constraints,
    prediction_views,
    timing_views,
)

app_name = "game"

urlpatterns = [
    path("", date_views.match_list, name="match_list"),
    path("coupon/create/", prediction_constraints.create_coupon, name="create_coupon"),
    path("timing/", timing_views.match_timing, name="match_timing"),
    path(
        "demand/<int:match_id>/",
        demand_views.prediction_request_state,
        name="prediction_request_state",
    ),
    path(
        "demand/<int:match_id>/toggle/",
        demand_views.toggle_prediction_request,
        name="toggle_prediction_request",
    ),
    path(
        "<str:sport>/<str:scope>/<slug:selected_date>/",
        date_views.match_list,
        name="match_list_filtered",
    ),
    path("<slug:slug>/predictions/", prediction_views.match_predictions, name="match_predictions"),
    path("<slug:slug>/", match_detail_views.match_detail, name="match_detail"),
]
