from django import forms
from django.utils import timezone
from django.db.models import Count
from .models import JobCard, JobCardLineItem, ServiceType
from clients.models import Client
from core.models import User
from django.forms import inlineformset_factory
import calendar


class OptionalModelChoiceField(forms.ModelChoiceField):
    """ModelChoiceField that safely handles empty string values."""
    def to_python(self, value):
        if value == '' or value is None:
            return None
        return super().to_python(value)


class JobCardForm(forms.ModelForm):
    class Meta:
        model = JobCard
        fields = [
            'client', 'assigned_to', 'priority', 'notes',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.order_by('full_name').annotate(prev_jobs=Count('job_cards'))
        self.fields['assigned_to'].queryset = User.objects.filter(
            is_active_staff=True, is_active=True).order_by('first_name')
        self.fields['assigned_to'].required = False
        self.fields['notes'].required = False


class JobCardLineItemForm(forms.ModelForm):
    service_type = OptionalModelChoiceField(
        queryset=ServiceType.objects.filter(is_active=True).order_by('category', 'name'),
        required=False,
        empty_label='Search services...'
    )

    period_month = forms.ChoiceField(required=False)
    period_year = forms.ChoiceField(required=False)

    class Meta:
        model = JobCardLineItem
        fields = [
            'service_type', 'custom_description', 'default_price',
            'negotiated_price', 'status', 'period_label', 'notes',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        this_year = timezone.now().year
        month_choices = [('', 'Month')] + [(i, calendar.month_name[i]) for i in range(1, 13)]
        # Default year choices (numeric) used for monthly/normal selection
        default_year_choices = [('', 'Year')] + [(y, y) for y in range(this_year - 1, this_year + 3)]
        year_choices = default_year_choices
        self.fields['period_month'].choices = month_choices
        self.fields['period_year'].choices = year_choices
        self.fields['period_month'].widget.attrs.update({'class': 'form-ctrl li-period-month'})
        self.fields['period_year'].widget.attrs.update({'class': 'form-ctrl li-period-year'})
        self.fields['service_type'].queryset = ServiceType.objects.filter(
            is_active=True).order_by('category', 'name')
        self.fields['custom_description'].required = False
        self.fields['default_price'].required = False
        self.fields['negotiated_price'].required = False
        self.fields['period_label'].required = False
        self.fields['notes'].required = False

        period_label = self.initial.get('period_label') or getattr(self.instance, 'period_label', '')
        if period_label:
            parts = period_label.split()
            if len(parts) >= 2:
                year = parts[-1]
                month = ' '.join(parts[:-1])
                month_map = {calendar.month_name[i]: str(i) for i in range(1, 13)}
                if month in month_map:
                    self.fields['period_month'].initial = month_map[month]
                    self.fields['period_year'].initial = year
        else:
            # If a service_type is provided (initial or instance), adapt year choices
            svc = None
            if 'service_type' in self.initial and self.initial.get('service_type'):
                try:
                    svc = ServiceType.objects.filter(pk=self.initial.get('service_type')).first()
                except Exception:
                    svc = None
            if not svc and getattr(self.instance, 'service_type', None):
                svc = getattr(self.instance, 'service_type')

            if svc:
                dt = getattr(svc, 'deadline_type', '')
                # Annual (Dec 31) should present two-year labels like 2024/25
                if dt == 'annual_dec31':
                    # present end-year values with labels like 2024/25
                    years = list(range(this_year - 1, this_year + 2))
                    two_year_choices = [('', 'Year')] + [(
                        y, f"{y-1}/{str(y)[-2:]}"
                    ) for y in years]
                    self.fields['period_year'].choices = two_year_choices
                    # default to most recent completed financial year (end year = this_year - 1)
                    self.fields['period_year'].initial = this_year - 1
                else:
                    # default numeric year choices
                    self.fields['period_year'].choices = default_year_choices
                    # default for monthly/normal: previous month/year
                    now = timezone.now()
                    prev_month = now.month - 1 or 12
                    prev_year = now.year if now.month > 1 else now.year - 1
                    self.fields['period_month'].initial = prev_month
                    self.fields['period_year'].initial = prev_year

    def clean(self):
        cleaned_data = super().clean()
        period_label = (cleaned_data.get('period_label') or '').strip()
        period_month = cleaned_data.get('period_month')
        period_year = cleaned_data.get('period_year')
        service_type = cleaned_data.get('service_type')
        deadline_type = getattr(service_type, 'deadline_type', '') if service_type else ''

        if not period_label and period_year:
            try:
                year = int(period_year)
            except (TypeError, ValueError):
                year = None

            if deadline_type.startswith('annual') and year is not None:
                cleaned_data['period_label'] = f"{year-1}/{year}"
            elif period_month:
                try:
                    cleaned_data['period_label'] = f"{calendar.month_name[int(period_month)]} {period_year}"
                except (ValueError, IndexError):
                    pass
        return cleaned_data


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
