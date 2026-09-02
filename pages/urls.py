from django.urls import path

from . import views

app_name = "pages"

urlpatterns = [
    path("help/<slug:key>/", views.help_content, name="help_content"),
]
