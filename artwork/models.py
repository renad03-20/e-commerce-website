from django.db import models
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFill
from django.utils.translation import gettext_lazy as _
from django.conf import settings

# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name
    def get_first_image_url(self):
        first_artwork = self.artwork_set.filter(image__isnull=False).first()
        if first_artwork and first_artwork.image:
            return first_artwork.image.url

        return '/static/img/category-placeholder.jpg' 

class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class Artwork(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='artwork/')
    
    # what the gallery will load
    thumbnail = ImageSpecField(source='image', 
                               processors=[ResizeToFill(300,300)],
                               format='JPEG',
                               options={'quality': 70})
    
    # for the detail page 
    thumbnail = ImageSpecField(source='image', 
                               processors=[ResizeToFill(800,800)],
                               format='JPEG',
                               options={'quality': 70})
    
    # Relationships
    artist = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='artworks')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True)
    
    # Extra data
    stock = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

class CustomRequest(models.Model):
    STATUS = [
        ('R', _('Requested')),
        ('A', _('Accepted')),
        ('D', _('Declined')),
        ('P', _('In Progress')),
        ('C', _('Completed'))
    ]
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='sent_requests'
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='received_requests'
    )
 
    reference_image = models.ImageField(upload_to='user_image_ref/')
    requirements = models.TextField(max_length=600)
    status = models.CharField(max_length=1, choices=STATUS, default="R")
    reason_for_declined = models.TextField(max_length=500, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True) 

    def __str__(self):
        return self.title
