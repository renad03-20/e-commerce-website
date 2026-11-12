from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User, Group
from .models import SupportMessage


class ContactForm(forms.ModelForm):
    class Meta:
        model = SupportMessage
        fields = ['name', 'email', 'subject', 'order_number', 'message']
        widgets = {'message': forms.Textarea(attrs={'rows': 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    is_artist = forms.BooleanField(
        required=False,
        label='I am an artist and want to sell my artwork'
    )
    
    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2", "is_artist")
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        
        if commit:
            user.save()
            
            # Add user to Artists group if they checked the box
            if self.cleaned_data.get('is_artist'):
                artists_group, created = Group.objects.get_or_create(name='Artists')
                user.groups.add(artists_group)
        
        return user
