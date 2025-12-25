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

class OrderShippingForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['tracking_number', 'shipping_carrier']
        widgets = {
            'tracking_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter tracking number'
            }),
            'shipping_carrier': forms.Select(attrs={'class': 'form-control'}, choices=[
                ('', 'Select carrier'),
                ('usps', 'USPS'),
                ('ups', 'UPS'),
                ('fedex', 'FedEx'),
                ('dhl', 'DHL'),
                ('other', 'Other'),
            ]),
        }

class OrderStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=OrderItem._meta.get_field('artist_fulfillment_status').choices,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    tracking_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Tracking number (optional)'
        })
    )
    shipping_carrier = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'Select carrier'),
            ('usps', 'USPS'),
            ('ups', 'UPS'),
            ('fedex', 'FedEx'),
            ('dhl', 'DHL'),
            ('other', 'Other'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'})
    )