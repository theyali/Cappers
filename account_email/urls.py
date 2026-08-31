from django.urls import path

from . import views


app_name = "account_email"

urlpatterns = [
    path("add/", views.add_email, name="add"),
    path("change/request/", views.request_email_change, name="request_change"),
    path("change/<str:token>/", views.confirm_change, name="confirm_change"),
    path("verify/<int:request_id>/", views.verify_new_email, name="verify"),
]
