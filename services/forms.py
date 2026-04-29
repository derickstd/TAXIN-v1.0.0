from django import forms
from .models import JobCard, JobCardLineItem, ServiceType
from clients.models import Client
from core.models import User
from django.forms import inlineformset_factory
import calendar


class JobCardForm(forms.ModelForm):
    class Meta:
        model = JobCard
        fields = [
            'client', 'period_month', 'period_year', 'assigned_to',
            'priority', 'due_date', 'notes', 'is_periodic',
        ]
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.order_by('full_name')
        self.fields['assigned_to'].queryset = User.objects.filter(
            is_active_staff=True, is_active=True).order_by('first_name')
        self.fields['assigned_to'].required = False
        self.fields['period_month'].required = False
        self.fields['period_year'].required = False
        self.fields['due_date'].required = False
        self.fields['notes'].required = False
        self.fields['is_periodic'].required = False
        month_choices = [('', '-- Month --')] + [(i, calendar.month_name[i]) for i in range(1, 13)]
        self.fields['period_month'].widget = forms.Select(choices=month_choices)


class JobCardLineItemForm(forms.ModelForm):
    class Meta:
        model = JobCardLineItem
        fields = [
            'service_type', 'custom_description', 'default_price',
            'negotiated_price', 'status', 'period_label', 'notes',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service_type'].queryset = ServiceType.objects.filter(
            is_active=True).order_by('category', 'name')
        self.fields['service_type'].required = False
        self.fields['custom_description'].required = False
        self.fields['default_price'].required = False
        self.fields['negotiated_price'].required = False
        self.fields['period_label'].required = False
        self.fields['notes'].required = False


class ServiceTypeForm(forms.ModelForm):
    class Meta:
        model = ServiceType
        fields = [
            'name', 'category', 'default_price', 'deadline_type',
            'is_recurring', 'vat_applicable', 'description',
        ]
        widgets = {
            'default_price': forms.NumberInput(attrs={'min': 0, 'step': 1000}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['default_price'].required = False

    def clean_default_price(self):
        price = self.cleaned_data.get('default_price')
        if price in (None, ''):
            return 0
        if price < 0:
            raise forms.ValidationError('Price cannot be negative.')
        return price


LineItemFormSet = inlineformset_factory(
    JobCard, JobCardLineItem,
    form=JobCardLineItemForm,
    extra=1,
    can_delete=True,
)
