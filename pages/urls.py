from django.urls import path, include
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("signup/", views.authview, name="authView"),
    path("accounts/", include("django.contrib.auth.urls")),
]