from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import Client, WalkInIntake
from core.models import User
from core.branch_access import get_entry_branch, scope_queryset


class OptionalModelChoiceField(forms.ModelChoiceField):
    """ModelChoiceField that safely handles empty string values."""
    def to_python(self, value):
        if value == '' or value is None:
            return None
        return super().to_python(value)


class ClientForm(forms.ModelForm):
    referred_by = OptionalModelChoiceField(
        queryset=Client.objects.order_by('full_name'),
        required=False,
        empty_label='— None —'
    )
    assigned_officer = OptionalModelChoiceField(
        queryset=User.objects.filter(is_active_staff=True, is_active=True).order_by('first_name'),
        required=False,
        empty_label='— None —'
    )
    class Meta:
        model = Client
        fields = [
            'client_type', 'full_name', 'tin',
            'phone_primary', 'phone_whatsapp', 'email',
            'physical_address', 'district',
            'referred_by', 'assigned_officer', 'notes',
        ]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.duplicate_branch = self.instance.branch
        else:
            self.duplicate_branch = get_entry_branch(user) if user else None
        self.fields['referred_by'].queryset = scope_queryset(
            user, Client.objects.order_by('full_name'),
        ) if user else Client.objects.order_by('full_name')
        self.fields['assigned_officer'].queryset = User.objects.filter(
            is_active_staff=True, is_active=True).order_by('first_name')
        if user and user.company_id and not user.is_superuser:
            if user.role in ('admin', 'ceo'):
                self.fields['assigned_officer'].queryset = self.fields['assigned_officer'].queryset.filter(company_id=user.company_id)
            else:
                self.fields['assigned_officer'].queryset = self.fields['assigned_officer'].queryset.filter(branch_id=user.branch_id)
        self.fields['tin'].required = False
        self.fields['phone_whatsapp'].required = False
        self.fields['email'].required = False
        self.fields['physical_address'].required = False
        self.fields['notes'].required = False

    def _same_branch_clients(self):
        clients = Client.objects.all()
        if self.duplicate_branch:
            return clients.filter(branch=self.duplicate_branch)
        return clients.filter(branch__isnull=True)

    def clean_tin(self):
        tin = self.cleaned_data.get('tin', '').strip()
        if tin:
            qs = self._same_branch_clients().filter(tin=tin)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError('A client with this TIN already exists.')
        return tin

    def clean_phone_primary(self):
        phone = self.cleaned_data.get('phone_primary', '').strip()
        if phone:
            qs = self._same_branch_clients().filter(
                Q(phone_primary=phone) | Q(phone_whatsapp=phone)
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError('A client with this phone number already exists.')
        return phone

    def clean_phone_whatsapp(self):
        whatsapp = self.cleaned_data.get('phone_whatsapp', '').strip()
        if whatsapp:
            qs = self._same_branch_clients().filter(
                Q(phone_primary=whatsapp) | Q(phone_whatsapp=whatsapp)
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError('This WhatsApp number is already used by another client.')
        return whatsapp


class WalkInIntakeForm(forms.ModelForm):
    service_type = OptionalModelChoiceField(
        queryset=None,  # Set in __init__
        required=False,
        empty_label='Select service...'
    )
    assigned_staff = OptionalModelChoiceField(
        queryset=None,  # Set in __init__
        required=False,
        empty_label='— None —'
    )

    class Meta:
        model = WalkInIntake
        fields = ['client', 'service_type', 'purpose', 'assigned_staff', 'notes', 'outcome']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from services.models import ServiceType
        
        self.fields['client'].queryset = scope_queryset(
            user, Client.objects.order_by('full_name'),
        ) if user else Client.objects.order_by('full_name')
        self.fields['client'].required = True
        service_types = ServiceType.objects.filter(is_active=True)
        if user:
            service_types = scope_queryset(user, service_types, branch_path='branches').distinct()
        self.fields['service_type'].queryset = service_types.order_by('category', 'name')
        self.fields['service_type'].label = 'Purpose of Visit'
        self.fields['purpose'].required = False
        self.fields['purpose'].widget = forms.HiddenInput()
        assigned_staff = User.objects.filter(
            is_active_staff=True, is_active=True).order_by('first_name')
        if user and user.company_id and not user.is_superuser:
            assigned_staff = assigned_staff.filter(
                company_id=user.company_id if user.role in ('admin', 'ceo') else None
            ) if user.role in ('admin', 'ceo') else assigned_staff.filter(branch_id=user.branch_id)
        self.fields['assigned_staff'].queryset = assigned_staff
        self.fields['notes'].required = False
        self.fields['outcome'].required = False

    def clean(self):
        cleaned_data = super().clean()
        # Validation: service_type or purpose must be provided
        service_type = cleaned_data.get('service_type')
        purpose = cleaned_data.get('purpose')
        if not service_type and not purpose:
            raise ValidationError('Please select a service or describe the purpose of the visit.')
        return cleaned_data
