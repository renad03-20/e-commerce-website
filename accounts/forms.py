from django import forms
from django.contrib.auth.forms import UserChangeForm
from .models import UserProfile, Address

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['phone_number', 'date_of_birth', 'avatar', 'bio', 'newsletter_subscription']
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'bio': forms.Textarea(attrs={'rows': 4}),
        }

class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['address_type', 'first_name', 'last_name', 'address_line_1', 
                 'address_line_2', 'city', 'state', 'postal_code', 'country', 'is_default']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control'})

class CommissionStatusForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['is_available_for_commissions']
        labels = {
            'is_available_for_commissions': 'Available for commissions'
        }