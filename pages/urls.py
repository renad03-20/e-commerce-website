from django.urls import path, include
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
    path("accounts/", include("django.contrib.auth.urls")),
    path('logout/', views.logoutpage, name='logout'),

    # legal pages 
    path("terms/", views.terms_of_service, name="terms_of_service"),
    path("privacy/", views.privacy_policy, name="privacy_policy"),
    path("contact/", views.contact, name="contact"),
]