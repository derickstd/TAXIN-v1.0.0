from django import forms
from django.utils import timezone

from billing.models import BranchDailySummary, BranchDailyTransaction
from .models import BranchAccountTransfer, BranchBalanceSheetEntry


class BranchDailySummaryForm(forms.ModelForm):
    class Meta:
        model = BranchDailySummary
        fields = [
            'branch', 'business_date', 'opening_balance', 'cash_inflow',
            'cash_outflow', 'closing_balance', 'notes',
        ]
        widgets = {
            'business_date': forms.DateInput(attrs={'type': 'date'}),
            'opening_balance': forms.NumberInput(attrs={
                'min': '0', 'step': '0.01', 'placeholder': 'e.g. 1,000,000',
            }),
            'cash_inflow': forms.NumberInput(attrs={
                'min': '0', 'step': '0.01', 'placeholder': 'e.g. 250,000',
            }),
            'cash_outflow': forms.NumberInput(attrs={
                'min': '0', 'step': '0.01', 'placeholder': 'e.g. 50,000',
            }),
            'closing_balance': forms.NumberInput(attrs={
                'min': '0', 'step': '0.01', 'placeholder': 'e.g. 1,200,000',
            }),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, branches, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = branches
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        if (
            not self.is_bound
            and not self.initial.get('branch')
            and not self.instance.pk
            and self.fields['branch'].queryset.count() == 1
        ):
            self.fields['branch'].initial = self.fields['branch'].queryset.first()
        self.fields['notes'].required = False
        for field in ('opening_balance', 'cash_inflow', 'cash_outflow', 'closing_balance'):
            self.fields[field].min_value = 0

    def clean_business_date(self):
        business_date = self.cleaned_data['business_date']
        if business_date > timezone.localdate():
            raise forms.ValidationError('A daily summary cannot be dated in the future.')
        return business_date


class BranchDailyTransactionForm(forms.ModelForm):
    class Meta:
        model = BranchDailyTransaction
        fields = [
            'branch', 'business_date', 'direction', 'category', 'description',
            'account', 'amount', 'reference',
        ]
        widgets = {
            'business_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.TextInput(attrs={
                'maxlength': '255',
                'placeholder': 'What was received or paid?',
            }),
            'amount': forms.NumberInput(attrs={
                'min': '0.01',
                'step': '0.01',
                'placeholder': 'e.g. 50,000 UGX',
            }),
            'reference': forms.TextInput(attrs={
                'maxlength': '100',
                'placeholder': 'Receipt or transaction reference (optional)',
            }),
        }

    def __init__(self, *args, branches, expense_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.expense_only = expense_only
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['branch'].queryset = branches.filter(external_reporting=True)
        categories = list(self.fields['category'].choices)
        if expense_only:
            categories = [
                choice for choice in categories
                if BranchDailyTransaction.CATEGORY_DIRECTIONS.get(choice[0]) == 'outflow'
            ]
        self.fields['category'].choices = [
            ('', 'Select a category'),
            *categories,
        ]
        if (
            not self.is_bound
            and not self.initial.get('branch')
            and self.fields['branch'].queryset.count() == 1
        ):
            self.fields['branch'].initial = self.fields['branch'].queryset.first()

    def clean_business_date(self):
        business_date = self.cleaned_data['business_date']
        if business_date > timezone.localdate():
            raise forms.ValidationError('A transaction cannot be dated in the future.')
        return business_date

    def clean_direction(self):
        direction = self.cleaned_data['direction']
        if self.expense_only and direction != 'outflow':
            raise forms.ValidationError('Expense entries must record money out.')
        return direction


class BranchBalanceSheetEntryForm(forms.ModelForm):
    class Meta:
        model = BranchBalanceSheetEntry
        fields = ['branch', 'as_of_date', 'category', 'account_name', 'amount', 'notes']
        widgets = {
            'as_of_date': forms.DateInput(attrs={'type': 'date'}),
            'account_name': forms.TextInput(attrs={'maxlength': '120'}),
            'amount': forms.NumberInput(attrs={
                'min': '0', 'step': '0.01', 'placeholder': 'e.g. 1,000,000',
            }),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, branches, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = branches
        self.fields['as_of_date'].initial = timezone.localdate()
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['notes'].required = False

    def clean_account_name(self):
        category = self.cleaned_data.get('category')
        standard_names = {
            'cash_on_hand': 'Cash at hand',
            'bank_deposit': 'Bank deposits',
            'mobile_money': 'Mobile money',
        }
        return standard_names.get(
            category, self.cleaned_data['account_name'].strip(),
        )


class BranchAccountTransferForm(forms.ModelForm):
    bank_charges = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        label='Bank charges',
        help_text='Optional bank fee, recorded separately as an expense.',
        widget=forms.NumberInput(attrs={
            'min': '0',
            'step': '0.01',
            'placeholder': 'e.g. 1,500',
            'data-money-input': 'true',
        }),
    )

    class Meta:
        model = BranchAccountTransfer
        fields = [
            'branch', 'transfer_date', 'source_account', 'destination_account',
            'amount', 'description', 'reference',
        ]
        widgets = {
            'transfer_date': forms.DateInput(attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={
                'min': '0.01', 'step': '0.01', 'placeholder': 'e.g. 500,000',
            }),
            'description': forms.TextInput(attrs={'maxlength': '255'}),
            'reference': forms.TextInput(attrs={'maxlength': '100'}),
        }

    def __init__(self, *args, branches, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = branches
        self.fields['transfer_date'].initial = timezone.localdate()
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['reference'].required = False

    def clean(self):
        cleaned_data = super().clean()
        source_account = cleaned_data.get('source_account')
        destination_account = cleaned_data.get('destination_account')
        if source_account and destination_account:
            if source_account == destination_account:
                self.add_error(
                    'destination_account',
                    'Choose an account different from the source account.',
                )
            elif 'bank' not in (source_account, destination_account):
                raise forms.ValidationError(
                    'An account transfer must move money to or from the bank.',
                )
        return cleaned_data
