from django import forms
from .models import Client, WalkInIntake
from core.models import User


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            'client_type', 'full_name', 'trading_name', 'tin',
            'phone_primary', 'phone_whatsapp', 'email',
            'physical_address', 'district',
            'referred_by', 'assigned_officer', 'notes',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['referred_by'].queryset = Client.objects.order_by('full_name')
        self.fields['referred_by'].required = False
        self.fields['assigned_officer'].queryset = User.objects.filter(
            is_active_staff=True, is_active=True).order_by('first_name')
        self.fields['assigned_officer'].required = False
        self.fields['trading_name'].required = False
        self.fields['tin'].required = False
        self.fields['phone_whatsapp'].required = False
        self.fields['email'].required = False
        self.fields['physical_address'].required = False
        self.fields['notes'].required = False


class WalkInIntakeForm(forms.ModelForm):
    class Meta:
        model = WalkInIntake
        fields = ['client', 'purpose', 'assigned_staff', 'notes', 'outcome']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.order_by('full_name')
        self.fields['assigned_staff'].queryset = User.objects.filter(
            is_active_staff=True, is_active=True).order_by('first_name')
        self.fields['assigned_staff'].required = False
        self.fields['notes'].required = False
