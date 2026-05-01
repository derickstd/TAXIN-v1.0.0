from django.db import models
from django.db import IntegrityError
from django.utils import timezone
from clients.models import Client
from services.models import JobCard
from core.models import User

class Invoice(models.Model):
    DOC_TYPE = [
        ('invoice',   'Tax Invoice'),
        ('proforma',  'Pro Forma Invoice'),
        ('quotation', 'Quotation'),
    ]
    STATUS = [
        ('draft','Draft'),('sent','Sent'),('partially_paid','Partially Paid'),
        ('paid','Paid'),('overdue','Overdue'),('written_off','Written Off'),
    ]
    PAYMENT_METHOD = [
        ('cash','Cash'),('mobile_money','Mobile Money'),
        ('bank_transfer','Bank Transfer'),('mixed','Mixed'),
    ]

    invoice_number  = models.CharField(max_length=30, unique=True, editable=False)
    document_type   = models.CharField(max_length=20, choices=DOC_TYPE, default='invoice')
    client          = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='invoices')
    job_card        = models.OneToOneField(JobCard, on_delete=models.CASCADE,
                                           related_name='invoice', null=True, blank=True)
    date_issued     = models.DateField(auto_now_add=True)
    due_date        = models.DateField()
    valid_until     = models.DateField(null=True, blank=True)   # for quotations
    subtotal        = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    vat_total       = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    grand_total     = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_paid     = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status          = models.CharField(max_length=20, choices=STATUS, default='draft')
    payment_method  = models.CharField(max_length=20, choices=PAYMENT_METHOD, blank=True)
    notes           = models.TextField(blank=True)
    sent_via_whatsapp = models.BooleanField(default=False)
    sent_at         = models.DateTimeField(null=True, blank=True)
    created_by      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_issued']

    @classmethod
    def number_prefix_for(cls, document_type):
        return {'invoice': 'INV', 'proforma': 'PRO', 'quotation': 'QUO'}.get(document_type, 'INV')

    @classmethod
    def next_invoice_number(cls, document_type, *, exclude_pk=None):
        year = timezone.now().year
        prefix = cls.number_prefix_for(document_type)
        qs = cls.objects.filter(invoice_number__startswith=f'{prefix}-{year}-')
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)

        max_num = 0
        for invoice_number in qs.values_list('invoice_number', flat=True):
            parts = (invoice_number or '').split('-')
            if len(parts) != 3 or parts[0] != prefix or parts[1] != str(year):
                continue
            try:
                max_num = max(max_num, int(parts[2]))
            except ValueError:
                continue
        return f'{prefix}-{year}-{max_num + 1:04d}'

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self.next_invoice_number(self.document_type, exclude_pk=self.pk)
        if not self.due_date:
            self.due_date = timezone.now().date() + timezone.timedelta(days=14)
        for _ in range(3):
            try:
                return super().save(*args, **kwargs)
            except IntegrityError as exc:
                if 'billing_invoice.invoice_number' not in str(exc) or self.pk:
                    raise
                self.invoice_number = self.next_invoice_number(self.document_type, exclude_pk=self.pk)
        return super().save(*args, **kwargs)

    @property
    def balance_due(self):
        return self.grand_total - self.amount_paid

    @property
    def balance(self):
        """Alias for balance_due for consistency"""
        return self.balance_due

    @property
    def days_overdue(self):
        if self.balance_due > 0 and timezone.now().date() > self.due_date:
            return (timezone.now().date() - self.due_date).days
        return 0

    @property
    def is_overdue(self):
        """Check if invoice is overdue"""
        return self.days_overdue > 0

    def aging_bucket(self):
        d = self.days_overdue
        if d == 0:   return 'Current'
        elif d <= 30: return '1–30 days'
        elif d <= 60: return '31–60 days'
        elif d <= 90: return '61–90 days'
        else:         return '90+ days'

    def update_status(self):
        if self.document_type in ('proforma', 'quotation'):
            if self.amount_paid >= self.grand_total and self.grand_total > 0:
                self.status = 'paid'
            elif self.amount_paid > 0:
                self.status = 'partially_paid'
            Invoice.objects.filter(pk=self.pk).update(status=self.status, amount_paid=self.amount_paid)
            return
        if self.amount_paid >= self.grand_total:
            self.status = 'paid'
        elif self.amount_paid > 0:
            self.status = 'partially_paid'
        elif self.status not in ('draft', 'written_off') and timezone.now().date() > self.due_date:
            self.status = 'overdue'
        Invoice.objects.filter(pk=self.pk).update(status=self.status, amount_paid=self.amount_paid)

    def get_doc_label(self):
        return dict(self.DOC_TYPE).get(self.document_type, 'Invoice')

    def __str__(self):
        return f"{self.invoice_number} — {self.client.get_display_name()}"


class Payment(models.Model):
    METHOD = [('cash','Cash'),('mobile_money','Mobile Money'),('bank_transfer','Bank Transfer')]
    invoice       = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount        = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date  = models.DateField(auto_now_add=True)
    method        = models.CharField(max_length=20, choices=METHOD, default='cash')
    reference     = models.CharField(max_length=100, blank=True)
    received_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    notes         = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    @property
    def receipt_number(self):
        """Generate receipt number from payment ID"""
        return f"RCT-{self.payment_date.year}-{self.pk:05d}"

    def get_payment_method_display(self):
        """Get human-readable payment method"""
        return dict(self.METHOD).get(self.method, self.method)

    def __str__(self):
        return f"UGX {self.amount:,.0f} → {self.invoice.invoice_number}"
