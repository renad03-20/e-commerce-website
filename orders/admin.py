from django.contrib import admin
from .models import Order, OrderItem

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    raw_id_fields = ['artwork']

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'first_name', 'last_name', 'email', 'city', 'paid', 'status', 'created']
    list_filter = ['paid', 'status', 'created', 'city']
    search_fields = ['first_name', 'last_name', 'email', 'id']
    inlines = [OrderItemInline]

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order', 'artwork', 'price', 'quantity']
    list_filter = ['order__paid']
    search_fields = ['artwork__title', 'order__id']