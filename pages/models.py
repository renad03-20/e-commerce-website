from django.db import models

class SupportMessage(models.Model):
    SUBJECTS = [
        ('general', 'General Inquiry'), ('artist', 'Artist Account'),
        ('order', 'Order Issue'), ('technical', 'Technical Problem'),
        ('refund', 'Refund Request'), ('partnership', 'Business Partnership'),
        ('other', 'Other'),
    ]
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=20, choices=SUBJECTS)
    order_number = models.CharField(max_length=30, blank=True)
    message = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.get_subject_display()} — {self.name}'
