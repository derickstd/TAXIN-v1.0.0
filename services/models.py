from django.db import models
from django.utils import timezone
from clients.models import Client
from core.models import User

class ServiceType(models.Model):
    CATEGORY = [
        ('ura_filing','URA Filing'),('nssf','NSSF'),('ursb','URSB'),
        ('ura_advisory','URA Advisory'),('immigration','Immigration'),
        ('customs','Customs'),('advisory','Advisory'),('miscellaneous','Miscellaneous'),
    ]
    DEADLINE_TYPE = [
        ('monthly_15','15th of Following Month'),
        ('annual_dec31','Annual — 31 December'),
        ('annual_jun30','Annual — 30 June'),
        ('annual_ursb','URSB Annual (12 months from incorporation)'),
        ('none','No Fixed Deadline'),
    ]
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=30, choices=CATEGORY)
    default_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deadline_type = models.CharField(max_length=20, choices=DEADLINE_TYPE, default='none')
    is_recurring = models.BooleanField(default=False)
    vat_applicable = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} (UGX {self.default_price:,.0f})"

class ClientServiceSubscription(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='subscriptions')
    service_type = models.ForeignKey(ServiceType, on_delete=models.CASCADE)
    negotiated_price = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(auto_now_add=True)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        unique_together = ('client', 'service_type')

    def __str__(self):
        return f"{self.client} — {self.service_type.name}"

class JobCard(models.Model):
    STATUS = [
        ('open','Open'),('in_progress','In Progress'),
        ('pending_payment','Pending Payment'),('completed','Completed'),('cancelled','Cancelled'),
    ]
    PRIORITY = [('normal','Normal'),('urgent','Urgent')]

    job_number = models.CharField(max_length=30, unique=True, editable=False)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='job_cards')
    period_month = models.IntegerField(null=True, blank=True)
    period_year = models.IntegerField(null=True, blank=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assigned_jobs')
    status = models.CharField(max_length=20, choices=STATUS, default='open')
    priority = models.CharField(max_length=10, choices=PRIORITY, default='normal')
    notes = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    is_periodic = models.BooleanField(default=False)
    total_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_jobs')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.job_number:
            from django.db.models import Max
            year = timezone.now().year
            prefix = f'JC-{year}-'
            agg = JobCard.objects.filter(job_number__startswith=prefix).aggregate(
                m=Max('job_number'))
            last_num = 0
            if agg['m']:
                try:
                    last_num = int(agg['m'].split('-')[-1])
                except (ValueError, IndexError):
                    last_num = 0
            self.job_number = f'{prefix}{last_num + 1:04d}'
        super().save(*args, **kwargs)

    def get_period_label(self):
        if self.period_month and self.period_year:
            from calendar import month_name
            return f"{month_name[self.period_month]} {self.period_year}"
        return "—"

    def update_total(self):
        total = sum(li.negotiated_price + li.vat_amount for li in self.line_items.all())
        self.total_fee = total
        JobCard.objects.filter(pk=self.pk).update(total_fee=total)

    def __str__(self):
        return f"{self.job_number} — {self.client.get_display_name()}"

class JobCardLineItem(models.Model):
    ITEM_STATUS = [
        ('handled_paid','Handled & Paid'),
        ('handled_not_paid','Handled — Awaiting Payment'),
        ('not_handled','Not Yet Handled'),
    ]
    job_card = models.ForeignKey(JobCard, on_delete=models.CASCADE, related_name='line_items')
    service_type = models.ForeignKey(ServiceType, on_delete=models.SET_NULL, null=True)
    custom_description = models.CharField(max_length=300, blank=True)
    default_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    negotiated_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=ITEM_STATUS, default='not_handled')
    period_label = models.CharField(max_length=50, blank=True)
    notes = models.CharField(max_length=300, blank=True)

    def get_description(self):
        return self.custom_description or (self.service_type.name if self.service_type else 'Custom Service')

    def line_total(self):
        return self.negotiated_price + self.vat_amount

    def __str__(self):
        return f"{self.get_description()} — UGX {self.negotiated_price:,.0f}"

class StaffActivityLog(models.Model):
    job_card = models.ForeignKey(JobCard, on_delete=models.CASCADE, related_name='activity_logs')
    staff = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
