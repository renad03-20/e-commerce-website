from django.contrib import admin
from .models import SupportMessage


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'subject', 'order_number', 'created_at', 'resolved']
    list_filter = ['resolved', 'subject', 'created_at']
    search_fields = ['name', 'email', 'order_number', 'message']
    readonly_fields = ['name', 'email', 'subject', 'order_number', 'message', 'created_at']
