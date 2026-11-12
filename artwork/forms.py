from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

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

    def clean_price(self):
        price = self.cleaned_data['price']
        if price <= 0:
            raise ValidationError('Enter an artwork price greater than zero.')
        return price


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
        error_messages = {
            'title': {'required': 'Enter a request title.'},
            'requirements': {'required': 'Describe what you would like the artist to create.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        self.fields['title'].label = 'Request title'
        self.fields['requirements'].label = 'What would you like the artist to create?'
        self.fields['reference_image'].label = 'Reference image (optional)'
        self.fields['budget'].label = 'Your budget in USD (optional)'
        self.fields['desired_deadline'].label = 'Preferred deadline (optional)'
        self.fields['budget'].widget.attrs['min'] = '0.01'
        self.fields['budget'].help_text = 'Leave blank if you are unsure. Otherwise, enter a budget greater than zero.'
        self.fields['desired_deadline'].widget.attrs['min'] = timezone.localdate().isoformat()
        self.fields['desired_deadline'].help_text = 'Choose today or a later date, or leave blank.'

    def clean_budget(self):
        budget = self.cleaned_data.get('budget')
        if budget is not None and budget <= 0:
            raise ValidationError(
                'Your budget must be greater than zero.',
                code='non_positive_budget',
            )
        return budget

    def clean_desired_deadline(self):
        deadline = self.cleaned_data.get('desired_deadline')
        if deadline is not None and deadline < timezone.localdate():
            raise ValidationError('Choose today or a later date for your preferred deadline.', code='past_deadline')
        return deadline


class CommissionAcceptForm(forms.Form):
    price = forms.DecimalField(
    max_digits=10,
    decimal_places=2,
    min_value=Decimal('0.50'),
    max_value=Decimal('999999.99'),
    error_messages={
        'min_value': 'The commission price must be at least USD 0.50 for payment.',
        'max_value': 'The commission price cannot exceed USD 999,999.99.',
    },
        )
    artist_deadline = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        self.fields['artist_deadline'].widget.attrs['min'] = timezone.localdate().isoformat()

    def clean_artist_deadline(self):
        deadline = self.cleaned_data.get('artist_deadline')
        if deadline is not None and deadline < timezone.localdate():
            raise ValidationError('Choose today or a later date for your deadline.')
        return deadline


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
