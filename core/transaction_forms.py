"""
Forms for duplicate client handling, transaction editing, and reporting.
"""

from django import forms
from django.contrib.auth.models import User
from core.models import DuplicateClientSuggestion, TransactionEditLog, ReportingSettings


class DuplicateClientMergeForm(forms.Form):
    """Form for merging duplicate clients."""
    
    action = forms.ChoiceField(
        choices=[
            ('merge', 'Merge the clients'),
            ('cancel', 'Cancel and mark as false positive'),
        ],
        widget=forms.RadioSelect(),
        label='Action'
    )
    
    keep_phone_from_duplicate = forms.BooleanField(
        required=False,
        label='Use phone from duplicate client'
    )
    
    keep_email_from_duplicate = forms.BooleanField(
        required=False,
        label='Use email from duplicate client'
    )
    
    keep_address_from_duplicate = forms.BooleanField(
        required=False,
        label='Use address from duplicate client'
    )
    
    keep_trading_name_from_duplicate = forms.BooleanField(
        required=False,
        label='Use trading name from duplicate client'
    )
    
    reason = forms.CharField(
        widget=forms.Textarea(),
        required=True,
        label='Reason for action',
        help_text='Explain why this action is being taken'
    )


class TransactionEditForm(forms.ModelForm):
    """Form for editing transaction details (superuser only)."""
    
    class Meta:
        model = TransactionEditLog
        fields = ['transaction_type', 'transaction_id', 'reason']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 4}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reason'].required = True
        self.fields['reason'].help_text = 'Provide a detailed reason for this edit for audit purposes'


class ReportingSettingsForm(forms.ModelForm):
    """Form for configuring reporting preferences."""
    
    class Meta:
        model = ReportingSettings
        fields = [
            'name',
            'report_types',
            'frequency',
            'email_recipients',
            'outstanding_threshold',
            'overdue_days_threshold',
            'is_active',
        ]
        widgets = {
            'report_types': forms.CheckboxSelectMultiple(choices=ReportingSettings.REPORT_TYPES),
            'email_recipients': forms.Textarea(attrs={'rows': 3, 'placeholder': 'email1@example.com\nemail2@example.com'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].help_text = 'Give this reporting configuration a descriptive name'
        self.fields['frequency'].help_text = 'How often should reports be generated?'
        self.fields['email_recipients'].help_text = 'Enter one email per line'
        
    def clean_email_recipients(self):
        """Parse email recipients from text area."""
        recipients_text = self.cleaned_data.get('email_recipients', '')
        if isinstance(recipients_text, str):
            emails = [email.strip() for email in recipients_text.split('\n') if email.strip()]
            # Validate emails
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError
            for email in emails:
                try:
                    validate_email(email)
                except ValidationError:
                    raise forms.ValidationError(f"Invalid email: {email}")
            return emails
        return recipients_text


class DuplicateDetectionFiltersForm(forms.Form):
    """Form for filtering duplicate client suggestions."""
    
    status = forms.MultipleChoiceField(
        choices=DuplicateClientSuggestion.STATUS_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        label='Status'
    )
    
    min_similarity = forms.IntegerField(
        min_value=0,
        max_value=100,
        initial=70,
        required=False,
        label='Minimum Similarity (%)'
    )
    
    sort_by = forms.ChoiceField(
        choices=[
            ('-similarity_score', 'Highest Similarity'),
            ('similarity_score', 'Lowest Similarity'),
            ('-created_at', 'Newest First'),
            ('created_at', 'Oldest First'),
        ],
        initial='-similarity_score',
        required=False,
        label='Sort By'
    )


class TransactionEditFieldsForm(forms.Form):
    """Dynamic form for editing specific transaction fields."""
    
    def __init__(self, transaction_obj, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.transaction_obj = transaction_obj
        self._populate_fields(transaction_obj)
    
    def _populate_fields(self, transaction_obj):
        """Populate form fields based on transaction type."""
        from billing.models import Invoice
        from services.models import JobCard
        from compliance.models import ComplianceDeadline
        
        if isinstance(transaction_obj, Invoice):
            self.fields['due_date'] = forms.DateField(
                initial=transaction_obj.due_date,
                label='Due Date',
                widget=forms.DateInput(attrs={'type': 'date'})
            )
            self.fields['status'] = forms.ChoiceField(
                choices=Invoice.STATUS,
                initial=transaction_obj.status,
                label='Status'
            )
            self.fields['notes'] = forms.CharField(
                widget=forms.Textarea(attrs={'rows': 4}),
                required=False,
                initial=transaction_obj.notes
            )
        
        elif isinstance(transaction_obj, JobCard):
            self.fields['status'] = forms.ChoiceField(
                choices=JobCard.STATUS,
                initial=transaction_obj.status,
                label='Status'
            )
            self.fields['due_date'] = forms.DateField(
                initial=transaction_obj.due_date,
                required=False,
                label='Due Date',
                widget=forms.DateInput(attrs={'type': 'date'})
            )
            self.fields['notes'] = forms.CharField(
                widget=forms.Textarea(attrs={'rows': 4}),
                required=False,
                initial=transaction_obj.notes
            )
        
        elif isinstance(transaction_obj, ComplianceDeadline):
            self.fields['status'] = forms.ChoiceField(
                choices=ComplianceDeadline.STATUS,
                initial=transaction_obj.status,
                label='Status'
            )
            self.fields['due_date'] = forms.DateField(
                initial=transaction_obj.due_date,
                label='Due Date',
                widget=forms.DateInput(attrs={'type': 'date'})
            )
            self.fields['notes'] = forms.CharField(
                widget=forms.Textarea(attrs={'rows': 4}),
                required=False,
                initial=transaction_obj.notes
            )
