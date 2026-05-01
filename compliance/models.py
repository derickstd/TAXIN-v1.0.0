from django.db import models
from clients.models import Client
from services.models import ServiceType, JobCard
from core.models import User

class ComplianceObligation(models.Model):
    FREQUENCY = [('monthly','Monthly'),('quarterly','Quarterly'),('annual','Annual')]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='obligations')
    service_type = models.ForeignKey(ServiceType, on_delete=models.CASCADE)
    frequency = models.CharField(max_length=20, choices=FREQUENCY, default='monthly')
    is_active = models.BooleanField(default=True)
    custom_deadline = models.DateField(null=True, blank=True)
    start_date = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ('client', 'service_type')

    def __str__(self):
        return f"{self.client} — {self.service_type.name}"

class ComplianceDeadline(models.Model):
    STATUS = [
        ('upcoming', 'Upcoming'),
        ('filed_and_paid', 'Filed and Paid'),
        ('filed_not_paid', 'Filed and Not Paid'),
        ('paid_not_filed', 'Paid but Not Filed'),
        ('none', 'None'),
        ('overdue', 'Overdue'),
        ('penalty_issued', 'Penalty Issued'),
        ('waived', 'Waived'),
    ]
    obligation = models.ForeignKey(ComplianceObligation, on_delete=models.CASCADE, related_name='deadlines')
    period_label = models.CharField(max_length=50)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS, default='upcoming')
    filed_date = models.DateField(null=True, blank=True)
    filed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    job_card = models.ForeignKey(JobCard, on_delete=models.SET_NULL, null=True, blank=True)
    invoice = models.ForeignKey('billing.Invoice', on_delete=models.SET_NULL, null=True, blank=True)
    penalty_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['due_date']
        unique_together = ('obligation', 'period_label')
    
    @property
    def client(self):
        return self.obligation.client if self.obligation else None
    
    @property
    def service_name(self):
        return self.obligation.service_type.name if self.obligation and self.obligation.service_type else ''
    
    @property
    def is_filed(self):
        return self.status in ('filed_and_paid', 'filed_not_paid')
    
    @property
    def days_until_due(self):
        """Calculate days until due date"""
        from django.utils import timezone
        today = timezone.now().date()
        delta = (self.due_date - today).days
        return delta

    def __str__(self):
        return f"{self.obligation.client} — {self.obligation.service_type.name} — {self.period_label}"
