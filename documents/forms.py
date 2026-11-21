from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from billing.models import (
    BranchDailySummary, BranchDailyTransaction, OtherIncome, Payment,
)
from expenses.models import Expense, ExpenseCategory
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
            'branch', 'business_date', 'direction', 'category',
            'expense_category', 'description', 'account', 'amount', 'reference',
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

    def __init__(
        self, *args, branches, expense_only=False,
        require_branch_selection=False, **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.expense_only = expense_only
        self.require_branch_selection = require_branch_selection
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['branch'].queryset = branches.filter(external_reporting=True)
        if expense_only:
            expense_categories = ExpenseCategory.objects.filter(is_active=True)
            if self.instance.pk and self.instance.expense_category_id:
                expense_categories = ExpenseCategory.objects.filter(
                    Q(is_active=True) | Q(pk=self.instance.expense_category_id),
                )
            self.fields['expense_category'].queryset = expense_categories.order_by('name')
            self.fields['expense_category'].required = not self.instance.pk
            self.fields['expense_category'].widget.attrs.update({
                'class': 'form-control s2',
                'data-ph': 'Search expense categories…',
            })
            self.fields['direction'].widget = forms.HiddenInput()
            self.fields['category'].widget = forms.HiddenInput()
            self.fields['category'].initial = 'operating_expense'
            self.fields['account'].widget.attrs.update({
                'class': 'form-control s2',
                'data-ph': 'Search accounts…',
            })
        else:
            self.fields.pop('expense_category')
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
            not require_branch_selection
            and not self.is_bound
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

    def clean_category(self):
        category = self.cleaned_data['category']
        if self.expense_only and category != 'operating_expense':
            raise forms.ValidationError('Branch expenses must be recorded as operating expenses.')
        return category


class LedgerPaymentEditForm(forms.ModelForm):
    amount = forms.DecimalField(
        min_value=Decimal('0.01'), max_digits=15, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'min': '0.01', 'step': '0.01', 'placeholder': 'e.g. 50,000',
        }),
    )

    class Meta:
        model = Payment
        fields = ['amount', 'payment_date', 'method', 'reference', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'min': '0.01', 'step': '0.01', 'placeholder': 'e.g. 50,000',
            }),
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'reference': forms.TextInput(attrs={'maxlength': '100'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class LedgerOtherIncomeEditForm(forms.ModelForm):
    amount = forms.DecimalField(
        min_value=Decimal('0.01'), max_digits=15, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'min': '0.01', 'step': '0.01', 'placeholder': 'e.g. 50,000',
        }),
    )

    class Meta:
        model = OtherIncome
        fields = [
            'source_name', 'category', 'amount', 'income_date',
            'collection_method', 'reference', 'description',
        ]
        widgets = {
            'amount': forms.NumberInput(attrs={
                'min': '0.01', 'step': '0.01', 'placeholder': 'e.g. 50,000',
            }),
            'income_date': forms.DateInput(attrs={'type': 'date'}),
            'reference': forms.TextInput(attrs={'maxlength': '100'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class LedgerExpenseEditForm(forms.ModelForm):
    amount = forms.DecimalField(
        min_value=Decimal('0.01'), max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'min': '0.01', 'step': '0.01', 'placeholder': 'e.g. 50,000',
        }),
    )

    class Meta:
        model = Expense
        fields = [
            'expense_date', 'category', 'description', 'amount',
            'payment_method', 'reference',
        ]
        widgets = {
            'expense_date': forms.DateInput(attrs={'type': 'date'}),
            'amount': forms.NumberInput(attrs={
                'min': '0.01', 'step': '0.01', 'placeholder': 'e.g. 50,000',
            }),
            'description': forms.Textarea(attrs={'rows': 3}),
            'reference': forms.TextInput(attrs={'maxlength': '100'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = ExpenseCategory.objects.order_by('name')
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


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


class BranchAccountTransferEditForm(forms.ModelForm):
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
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['reference'].required = False
