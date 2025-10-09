from django.db import models
from django.conf import settings
from artwork.models import Artwork

class Order(models.Model):
    #! user information for logged in users 
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    #! customer information
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField()

    #! shipping address
    address = models.CharField(max_length=250)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=50)
    country = models.CharField(max_length=100)

    #! order details
    created = models.DateField(auto_now_add=True)

    updated = models.DateTimeField(auto_now=True)
    paid = models.BooleanField(default=False)

    #! payment information 
    stripe_payment_intent_id = models.CharField(max_length=100, blank=True)
    stripe_charge_id = models.CharField(max_length=100, blank=True)

    #! order status
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f"Order {self.id} - {self.first_name} {self.last_name}"
    
    def get_total_cost(self):
        return sum(item.get_cost() for item in self.items.all())
    
    def get_total_quantity(self):
        return sum(item.quantity for item in self.items.all())
    
class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    artwork_title = models.CharField(max_length=255, blank=True)
    artist_name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f'{self.artwork_title} ({self.quantity})'
    
    def get_cost(self):
        return self.price * self.quantity
    
    def save(self, *args, **kwargs):
        #! Store artwork details at time of purchase
        if not self.artwork_title:
            self.artwork_title = self.artwork.title
        if not self.artist_name:
            self.artist_name = self.artwork.artist.username
        super().save(*args, **kwargs)