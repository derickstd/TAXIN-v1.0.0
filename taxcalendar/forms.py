from django import forms
from .models import TaxEvent
from core.models import User
from core.branch_access import accessible_branches


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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        assigned_users = User.objects.filter(is_active_staff=True, is_active=True)
        if user and not (user.is_superuser or user.role in ('admin', 'ceo')):
            assigned_users = assigned_users.filter(branch__in=accessible_branches(user))
        elif user and not user.is_superuser and user.company_id:
            assigned_users = assigned_users.filter(company_id=user.company_id)
        self.fields['assigned_to'].queryset = assigned_users.order_by('first_name')
        self.fields['description'].required = False
