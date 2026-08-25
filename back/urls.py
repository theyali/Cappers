from django.urls import path

from . import views

app_name = "back"

urlpatterns = [
    path("health/", views.ajax_health, name="ajax_health"),
]
