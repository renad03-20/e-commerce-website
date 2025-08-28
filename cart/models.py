from django.db import models
from products.models import Product
# Create your models here.

class Cart(models.Model):
    created = models.DateTimeField(auto_now_add=True)

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name ="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveBigIntegerField(default=1)

    def __str__(self):
        return f'{self.quantity} X {self.product.name}'
    
    def get_total_price(self):
        return self.product.price * self.quantity