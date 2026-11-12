from django import forms
from .models import Order, OrderItem

class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['first_name', 'last_name', 'email', 'address', 'city', 'postal_code', 'country']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Street Address'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Postal Code'}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Country'}),
        }
    
    def __init__(self, *args, **kwargs):
        super(OrderCreateForm, self).__init__(*args, **kwargs)
        #! Set required to True for all fields
        for field in self.fields:
            self.fields[field].required = True

CARRIER_CHOICES = [
    ('', 'Select carrier'), ('usps', 'USPS'), ('ups', 'UPS'),
    ('fedex', 'FedEx'), ('dhl', 'DHL'), ('other', 'Other'),
]


class OrderShippingForm(forms.Form):
    tracking_number = forms.CharField(
        required=False, max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter tracking number'}),
    )
    shipping_carrier = forms.ChoiceField(
        required=False, choices=CARRIER_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )


class OrderStatusForm(OrderShippingForm):
    status = forms.ChoiceField(
        choices=OrderItem._meta.get_field('artist_fulfillment_status').choices,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    artist_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
