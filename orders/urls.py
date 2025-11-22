from django.urls import path
from . import views

urlpatterns = [
    path('create/', views.order_create, name='order_create'),
    path('created/<str:order_number>/', views.order_created, name='order_created'),
    path('history/', views.order_list, name='order_list'),
    path('<str:order_number>/', views.order_detail, name='order_detail'),
    path('artist/orders/', views.artist_orders, name='artist_orders'),
    
    # Payment URLs
    path('payment/process/', views.payment_process, name='payment_process'),
    path('payment/completed/', views.payment_completed, name='payment_completed'),
    path('payment/canceled/', views.payment_canceled, name='payment_canceled'),

    # aritst order management urls
    path('artist/dashboard/', views.artist_orders_dashboard, name='artist_orders_dashboard'),
    path('artist/order/<str:order_number>/', views.artist_order_detail, name='artist_order_detail'),
    path('artist/order/<str:order_number>/ship/', views.mark_order_shipped, name='mark_order_shipped'),
    path('artist/analytics/', views.artist_sales_analytics, name='artist_sales_analytics'),
]