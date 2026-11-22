from django import forms
from clients.models import Client
from core.branch_access import accessible_branches, scope_queryset
from core.models import Branch
from .models import Invoice, Payment


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            'client', 'document_type', 'due_date', 'valid_until',
            'subtotal', 'vat_total', 'grand_total', 'status', 'notes',
        ]
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['client'].queryset = scope_queryset(
                user, self.fields['client'].queryset,
            )
        for field in self.fields.values():
            widget = field.widget
            if not widget.attrs.get('class'):
                widget.attrs['class'] = 'form-control'
        self.fields['notes'].required = False
        self.fields['due_date'].required = False
        self.fields['valid_until'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk and self.instance.payments.exists():
            changed_amount_fields = [f for f in ('subtotal', 'vat_total', 'grand_total') if f in self.changed_data]
            if changed_amount_fields:
                raise forms.ValidationError(
                    'Cannot modify invoice amounts once payments have been recorded. '
                    'Update due date, notes, or status instead.'
                )
        grand_total = cleaned_data.get('grand_total')
        if grand_total is not None and self.instance.pk:
            amount_paid = self.instance.amount_paid
            if amount_paid > grand_total:
                raise forms.ValidationError(
                    'Grand total cannot be less than the amount already paid.'
                )
        return cleaned_data


class PaymentReceiptFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        label='Search',
        max_length=200,
        widget=forms.SearchInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search receipt, invoice, client, service, or reference',
        }),
    )
    date_from = forms.DateField(
        required=False,
        label='From',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    date_to = forms.DateField(
        required=False,
        label='To',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    method = forms.ChoiceField(
        required=False,
        label='Method',
        choices=[('', 'All methods')] + Payment.METHOD,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    branch = forms.ModelChoiceField(
        required=False,
        label='Branch',
        queryset=Branch.objects.none(),
        empty_label='All accessible branches',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = accessible_branches(user).order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        if date_from and date_to and date_from > date_to:
            self.add_error('date_to', 'The end date must be on or after the start date.')
        return cleaned_data
