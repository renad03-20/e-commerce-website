from django.contrib import admin
from .models import Artwork, Category, Tag

@admin.register(Artwork)
class ArtworkAdmin(admin.ModelAdmin):
    list_display = ('title', 'price', 'artist', 'category', 'stock', 'created_at')
    search_fields = ('title', 'artist__username')
    list_filter = ('category', 'tags', 'created_at')

admin.site.register(Category)
admin.site.register(Tag)    