from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("checkout/<slug:purpose>/", views.checkout, name="checkout"),
    path("<uuid:public_id>/return/", views.payment_return, name="return"),
    path("<uuid:public_id>/status/", views.payment_status, name="status"),
    path("webhooks/<slug:provider_code>/<slug:event_type>/", views.provider_webhook, name="webhook"),
]
