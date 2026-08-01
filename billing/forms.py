from django import forms
from .models import Invoice


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
