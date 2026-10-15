from django import forms
from django.core.exceptions import ValidationError

from .models import (
    Artwork,
    Category,
    Tag,
    CustomRequest,
    CommissionMessage,
    CommissionDelivery,
    CommissionRevisionRequest,
)


class ArtworkForm(forms.ModelForm):
    class Meta:
        model = Artwork
        fields = ['title', 'description', 'price', 'image', 'category', 'tags', 'stock']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'tags': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.all()
        self.fields['tags'].queryset = Tag.objects.all()


class CommissionRequestForm(forms.ModelForm):
    class Meta:
        model = CustomRequest
        fields = ['title', 'requirements', 'reference_image', 'budget', 'desired_deadline']
        widgets = {
            'requirements': forms.Textarea(
                attrs={'rows': 4, 'placeholder': 'Describe your vision (style, size, colors)...'}
            ),
            'desired_deadline': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


class CommissionAcceptForm(forms.Form):
    price = forms.DecimalField(max_digits=10, decimal_places=2)
    artist_deadline = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


class CommissionDeclineForm(forms.Form):
    reason_for_declined = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'rows': 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


class CommissionMessageForm(forms.ModelForm):
    class Meta:
        model = CommissionMessage
        fields = ['body', 'attachment']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Write a message...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


class CommissionDeliveryForm(forms.ModelForm):
    class Meta:
        model = CommissionDelivery
        fields = ['message', 'delivery_file', 'external_link']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Delivery notes...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

    def clean(self):
        cleaned_data = super().clean()
        delivery_file = cleaned_data.get('delivery_file')
        external_link = cleaned_data.get('external_link')
        if not delivery_file and not external_link:
            raise ValidationError('Provide a file or an external link for delivery.')
        return cleaned_data


class CommissionRevisionRequestForm(forms.ModelForm):
    class Meta:
        model = CommissionRevisionRequest
        fields = ['message']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe the changes you need...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


class CommissionCancelForm(forms.Form):
    cancel_reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
