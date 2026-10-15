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
    STATUS_REQUESTED = 'requested'
    STATUS_DECLINED = 'declined'
    STATUS_AWAITING_PAYMENT = 'awaiting_payment'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_DELIVERED = 'delivered'
    STATUS_REVISION_REQUESTED = 'revision_requested'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELED = 'canceled'

    STATUS = [
        (STATUS_REQUESTED, _('Requested')),
        (STATUS_DECLINED, _('Declined')),
        (STATUS_AWAITING_PAYMENT, _('Awaiting Payment')),
        (STATUS_IN_PROGRESS, _('In Progress')),
        (STATUS_DELIVERED, _('Delivered')),
        (STATUS_REVISION_REQUESTED, _('Revision Requested')),
        (STATUS_COMPLETED, _('Completed')),
        (STATUS_CANCELED, _('Canceled')),
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
 
    title = models.CharField(max_length=200)
    reference_image = models.ImageField(upload_to='commission_refs/', blank=True, null=True)
    requirements = models.TextField(max_length=600)
    budget = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    desired_deadline = models.DateField(blank=True, null=True)
    artist_deadline = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS, default=STATUS_REQUESTED)
    reason_for_declined = models.TextField(max_length=500, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    revision_limit = models.PositiveIntegerField(default=2)
    revision_count = models.PositiveIntegerField(default=0)
    stripe_payment_intent_id = models.CharField(max_length=200, blank=True)
    stripe_checkout_session_id = models.CharField(max_length=200, blank=True)
    accepted_at = models.DateTimeField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    canceled_at = models.DateTimeField(blank=True, null=True)
    cancel_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Commission #{self.id} - {self.title}"

    def is_participant(self, user):
        return user == self.sender or user == self.receiver

    def can_request_revision(self):
        return self.revision_count < self.revision_limit


class CommissionMessage(models.Model):
    commission = models.ForeignKey(CustomRequest, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='commission_messages')
    body = models.TextField(max_length=2000)
    attachment = models.FileField(upload_to='commission_messages/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message by {self.sender} on {self.created_at:%Y-%m-%d}"


class CommissionDelivery(models.Model):
    commission = models.ForeignKey(CustomRequest, on_delete=models.CASCADE, related_name='deliveries')
    delivered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='commission_deliveries')
    message = models.TextField(max_length=2000, blank=True)
    delivery_file = models.FileField(upload_to='commission_deliveries/', blank=True, null=True)
    external_link = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Delivery for Commission #{self.commission_id}"


class CommissionRevisionRequest(models.Model):
    commission = models.ForeignKey(CustomRequest, on_delete=models.CASCADE, related_name='revisions')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='commission_revisions')
    message = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Revision request for Commission #{self.commission_id}"


class CommissionStatusHistory(models.Model):
    commission = models.ForeignKey(CustomRequest, on_delete=models.CASCADE, related_name='status_history')
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Status change for Commission #{self.commission_id}"
