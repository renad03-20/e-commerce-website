from django.db import models
from django.conf import settings
from artwork.models import Artwork  
from decimal import Decimal

class Cart(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.user:
            return f"Cart of {self.user.username}"
        return f"Anonymous Cart ({self.session_key})"
    
    def get_total_price(self):
        """Sum of all item prices"""
        return sum(item.get_total_price() for item in self.items.all())
    
    def get_total_quantity(self):
        return sum(item.quantity for item in self.items.all())

    def get_tax(self):
        return self.get_total_price() * Decimal('0.08')

    def get_shipping(self):
        return Decimal('10.00')

    def get_grand_total(self):
        return self.get_total_price() + self.get_tax() + self.get_shipping()

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE)  # Changed from Product to Artwork
    quantity = models.PositiveIntegerField(default=1)  # Changed from PositiveBigIntegerField
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('cart', 'artwork')  # Prevents duplicate items in cart

    def __str__(self):
        return f'{self.quantity} x {self.artwork.title}'
    
    def get_total_price(self):
        return self.artwork.price * self.quantity