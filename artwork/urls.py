from django.urls import path
from . import views

urlpatterns = [
    path('artwork_list/', views.artwork_list, name='artwork_list'),
    path('create/', views.artwork_create, name='artwork_create'),

    path('artist/<int:artist_id>/', views.user_view_of_artist, name='user_view_of_artist'),

    path('<int:pk>/', views.artwork_detail, name='artwork_detail'),
    path('<int:pk>/update/', views.artwork_update, name='artwork_update'),
    path('<int:pk>/delete/', views.artwork_delete, name='artwork_delete'),

    path('artist_dashboard/', views.artist_dashboard, name='artist_dashboard'),
]
