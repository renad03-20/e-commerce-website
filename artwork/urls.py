from django.urls import path
from . import views

urlpatterns = [
    path('commissions/<int:commission_id>/start/', views.commission_start_work, name='commission_start_work'),
    path('artwork_list/', views.artwork_list, name='artwork_list'),
    path('create/', views.artwork_create, name='artwork_create'),

    path('artist/<int:artist_id>/', views.user_view_of_artist, name='user_view_of_artist'),

    path('<int:pk>/', views.artwork_detail, name='artwork_detail'),
    path('<int:pk>/update/', views.artwork_update, name='artwork_update'),
    path('<int:pk>/delete/', views.artwork_delete, name='artwork_delete'),

    path('artist_dashboard/', views.artist_dashboard, name='artist_dashboard'),

    # Commission workflow
    path('commissions/', views.commission_list, name='commission_list'),
    path('commissions/<int:commission_id>/', views.commission_detail, name='commission_detail'),
    path('commissions/<int:commission_id>/message/', views.commission_message_create, name='commission_message'),
    path('commissions/<int:commission_id>/accept/', views.commission_accept, name='commission_accept'),
    path('commissions/<int:commission_id>/decline/', views.commission_decline, name='commission_decline'),
    path('commissions/<int:commission_id>/cancel/', views.commission_cancel, name='commission_cancel'),
    path('commissions/<int:commission_id>/pay/', views.commission_payment_start, name='commission_payment_start'),
    path('commissions/<int:commission_id>/payment/completed/', views.commission_payment_completed, name='commission_payment_completed'),
    path('commissions/<int:commission_id>/payment/canceled/', views.commission_payment_canceled, name='commission_payment_canceled'),
    path('commissions/<int:commission_id>/deliver/', views.commission_delivery_create, name='commission_delivery'),
    path('commissions/<int:commission_id>/revision/', views.commission_request_revision, name='commission_revision_request'),
    path('commissions/<int:commission_id>/complete/', views.commission_mark_complete, name='commission_mark_complete'),
]
