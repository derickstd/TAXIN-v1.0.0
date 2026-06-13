from django import forms
from .models import TaxEvent
from core.models import User


class OptionalModelChoiceField(forms.ModelChoiceField):
    """ModelChoiceField that safely handles empty string values."""
    def to_python(self, value):
        if value == '' or value is None:
            return None
        return super().to_python(value)


class TaxEventForm(forms.ModelForm):
    assigned_to = OptionalModelChoiceField(
        queryset=None,  # Set in __init__
        required=False,
        empty_label='— None —'
    )

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
        self.fields['description'].required = False
