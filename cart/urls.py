from django.urls import path
from . import views

app_name = 'cart'

urlpatterns = [
    path('cart_detail/', views.cart_detail, name='cart_detail'),
    path('add/<int:artwork_id>/', views.add_to_cart_view, name='add_to_cart'),
    path('remove/<int:item_id>/', views.remove_from_cart_view, name='remove_from_cart'),
    path('update/<int:item_id>/', views.update_cart_view, name='update_cart'),
    path('checkout/', views.checkout, name='checkout'),
]