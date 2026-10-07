from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("webhooks/<slug:provider_code>/<slug:event_type>/", views.provider_webhook, name="webhook"),
]
