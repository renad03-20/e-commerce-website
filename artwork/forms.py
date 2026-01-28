from django import forms
from .models import Artwork, Category, Tag, CustomRequest

class ArtworkForm(forms.ModelForm):
    class Meta:
        model = Artwork
        fields = ['title', 'description', 'price', 'image', 'category', 'tags', 'stock']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'tags': forms.CheckboxSelectMultiple,
        }
    
    def __init__(self, *args, **kwargs):
        super(ArtworkForm, self).__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()
        self.fields['tags'].queryset = Tag.objects.all()

from django import forms
from .models import CustomRequest

class CustomRequestForm(forms.ModelForm):
    class Meta:
        model = CustomRequest
        # Only show fields the BUYER needs to fill out
        fields = ['reference_image', 'requirements']
        widgets = {
            'requirements': forms.Textarea(attrs={
                'rows': 4, 
                'placeholder': 'Describe your vision (colors, style, size)...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super(CustomRequestForm, self).__init__(*args, **kwargs)
        # Add Bootstrap or custom classes here if needed
        self.fields['reference_image'].widget.attrs.update({'class': 'form-control'})
        self.fields['requirements'].widget.attrs.update({'class': 'form-control'})