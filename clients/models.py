from django.db import models
from django.utils import timezone
from core.models import User

class Client(models.Model):
    CLIENT_TYPE = [('individual','Individual'),('company','Company'),('ngo','NGO'),('partnership','Partnership')]
    STATUS = [('active','Active'),('dormant','Dormant'),('suspended','Suspended'),('blacklisted','Blacklisted')]

    client_id = models.CharField(max_length=20, unique=True, editable=False)
    client_type = models.CharField(max_length=20, choices=CLIENT_TYPE, default='individual')
    full_name = models.CharField(max_length=200)
    trading_name = models.CharField(max_length=200, blank=True)
    tin = models.CharField(max_length=50, blank=True, unique=False, verbose_name='TIN')
    phone_primary = models.CharField(max_length=20)
    phone_whatsapp = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    physical_address = models.CharField(max_length=300, blank=True)
    district = models.CharField(max_length=100, default='Kampala')
    date_registered = models.DateField(auto_now_add=True)
    referred_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='referrals')
    assigned_officer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assigned_clients')
    status = models.CharField(max_length=20, choices=STATUS, default='active')
    notes = models.TextField(blank=True)
    total_outstanding = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    last_transaction_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_clients')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.client_id:
            from django.db.models import Max
            max_id = Client.objects.aggregate(m=Max('id'))['m'] or 0
            self.client_id = f'TX-{max_id + 1:04d}'
        super().save(*args, **kwargs)

    def get_display_name(self):
        return self.trading_name or self.full_name

    def __str__(self):
        return f"{self.client_id} — {self.get_display_name()}"

    def get_whatsapp_number(self):
        return self.phone_whatsapp or self.phone_primary

class WalkInIntake(models.Model):
    OUTCOME = [('pending','Pending'),('job_created','Job Created'),('declined','Declined'),('referred','Referred')]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='walkin_intakes')
    visit_date = models.DateTimeField(auto_now_add=True)
    purpose = models.TextField()
    assigned_staff = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    notes = models.TextField(blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Walk-in: {self.client} on {self.visit_date.date()}"
