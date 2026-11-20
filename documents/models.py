from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from clients.models import Client
from services.models import JobCard
from core.models import Branch, User


class ClientDocument(models.Model):
    DOC_TYPE = [
        ('filed_return', 'Filed Return'),
        ('acknowledgement', 'URA Acknowledgement'),
        ('source_doc', 'Source Document'),
        ('correspondence', 'Correspondence'),
        ('engagement_letter', 'Engagement Letter'),
        ('other', 'Other'),
    ]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='documents')
    job_card = models.ForeignKey(JobCard, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    doc_type = models.CharField(max_length=30, choices=DOC_TYPE, default='other')
    title = models.CharField(max_length=300)
    file = models.FileField(upload_to='client_docs/%Y/%m/')
    period_label = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.client} — {self.title}"


class BranchBalanceSheetEntry(models.Model):
    CATEGORY_TYPES = {
        'cash_on_hand': 'asset',
        'bank_deposit': 'asset',
        'mobile_money': 'asset',
        'other_debtor': 'asset',
        'fixed_asset': 'asset',
        'other_asset': 'asset',
        'creditor': 'liability',
        'loan_payable': 'liability',
        'tax_payable': 'liability',
        'other_liability': 'liability',
        'owner_capital': 'equity',
        'retained_earnings': 'equity',
        'other_equity': 'equity',
    }
    CATEGORY_CHOICES = [
        ('cash_on_hand', 'Cash at hand'),
        ('bank_deposit', 'Bank deposits'),
        ('mobile_money', 'Mobile money'),
        ('other_debtor', 'Other debtors'),
        ('fixed_asset', 'Fixed assets'),
        ('other_asset', 'Other assets'),
        ('creditor', 'Creditors / accounts payable'),
        ('loan_payable', 'Loans payable'),
        ('tax_payable', 'Tax payable'),
        ('other_liability', 'Other liabilities'),
        ('owner_capital', 'Owner capital'),
        ('retained_earnings', 'Retained earnings'),
        ('other_equity', 'Other equity'),
    ]

    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='balance_sheet_entries',
    )
    account_name = models.CharField(max_length=120)
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES)
    amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    as_of_date = models.DateField()
    notes = models.TextField(blank=True)
    entered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='balance_sheet_entries',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'account_name', '-as_of_date']
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'category', 'account_name', 'as_of_date'],
                name='unique_branch_account_balance_date',
            ),
        ]
        indexes = [models.Index(fields=['branch', 'as_of_date'])]

    @property
    def account_type(self):
        return self.CATEGORY_TYPES[self.category]

    def clean(self):
        if self.as_of_date and self.as_of_date > timezone.localdate():
            raise ValidationError({'as_of_date': 'A balance cannot be dated in the future.'})
        if self.account_name:
            self.account_name = self.account_name.strip()
            if not self.account_name:
                raise ValidationError({'account_name': 'Enter an account name.'})

    def __str__(self):
        return f'{self.branch.name} — {self.account_name}: {self.amount:,.2f}'


class BranchAccountTransfer(models.Model):
    ACCOUNT_CHOICES = [
        ('cash', 'Cash at hand'),
        ('petty_cash', 'Petty cash'),
        ('mobile_money', 'Mobile money'),
        ('bank', 'Bank'),
    ]
    SOURCE_ACCOUNT = ACCOUNT_CHOICES

    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name='account_transfers',
    )
    transfer_date = models.DateField()
    source_account = models.CharField(max_length=20, choices=SOURCE_ACCOUNT)
    destination_account = models.CharField(
        max_length=20, choices=ACCOUNT_CHOICES, default='bank',
    )
    amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    description = models.CharField(max_length=255, default='Account transfer')
    reference = models.CharField(max_length=100, blank=True)
    entered_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='account_transfers',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transfer_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'transfer_date', 'reference'],
                condition=~models.Q(reference=''),
                name='unique_branch_transfer_reference',
            ),
            models.CheckConstraint(
                condition=~models.Q(source_account=models.F('destination_account')),
                name='branch_transfer_distinct_accounts',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_account='bank')
                    | models.Q(destination_account='bank')
                ),
                name='branch_transfer_involves_bank',
            ),
        ]
        indexes = [models.Index(fields=['branch', 'transfer_date'])]

    def clean(self):
        if self.transfer_date and self.transfer_date > timezone.localdate():
            raise ValidationError({'transfer_date': 'A transfer cannot be dated in the future.'})
        if self.source_account == self.destination_account:
            raise ValidationError({
                'destination_account': 'Choose an account different from the source account.',
            })
        if 'bank' not in (self.source_account, self.destination_account):
            raise ValidationError(
                'An account transfer must move money to or from the bank.',
            )

    def __str__(self):
        return (
            f'{self.branch.name} — {self.get_source_account_display()} to '
            f'{self.get_destination_account_display()}: {self.amount:,.2f}'
        )
