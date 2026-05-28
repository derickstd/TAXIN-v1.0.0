from django import forms
from .models import TaxEvent
from core.models import User


class TaxEventForm(forms.ModelForm):
    class Meta:
        model = TaxEvent
        fields = ['title', 'event_type', 'due_date', 'description', 'assigned_to', 'status']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = User.objects.filter(is_active_staff=True, is_active=True).order_by('first_name')
        self.fields['assigned_to'].required = False
        self.fields['description'].required = False
