from django.urls import path
from . import views

#! url configration
urlpatterns = [
    path('hello/', views.say_hello)
]
