from django.contrib.auth.models import AbstractUser
from django.db import models
from django.contrib.contenttypes.models import ContentType


class Company(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    registration_number = models.CharField(max_length=100, blank=True)
    tin = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    db_name = models.CharField(max_length=255, blank=True, help_text='Optional database alias or filename for company-specific DB')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='owned_companies')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractUser):
    ROLE_CHOICES = [
        ('receptionist', 'Receptionist'),
        ('tax_officer',  'Tax Officer'),
        ('senior_officer','Senior Officer'),
        ('manager',      'Manager'),
        ('admin',        'Admin'),
    ]
    THEME_CHOICES = [
        ('ocean',    'Ocean Teal'),
        ('dark',     'Dark Mode'),
    ]
    role              = models.CharField(max_length=20, choices=ROLE_CHOICES, default='tax_officer')
    phone_whatsapp    = models.CharField(max_length=20, blank=True,
                                         help_text='WhatsApp number used for sending reminders (e.g. +256785230670)')
    email_notify      = models.EmailField(blank=True,
                                          help_text='Email used for sending communications (e.g. taxissues.go@gmail.com)')
    is_active_staff   = models.BooleanField(default=True)
    date_joined_firm  = models.DateField(null=True, blank=True)
    receive_debt_alerts = models.BooleanField(default=True,
                                               help_text='Receive Saturday/Monday debt reports')
    receive_task_reminders = models.BooleanField(default=True,
                                                  help_text='Receive reminders for incomplete tasks')
    ui_theme          = models.CharField(max_length=20, choices=THEME_CHOICES, default='ocean')
    company           = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL, related_name='users')

    def is_manager_or_admin(self):
        return self.is_superuser or self.role in ('manager', 'admin')

    def get_notify_whatsapp(self):
        """Return WhatsApp number for notifications, falling back to phone_whatsapp."""
        return self.phone_whatsapp or ''

    def get_notify_email(self):
        return self.email_notify or self.email or ''

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"


class AuditLog(models.Model):
    ACTION_CHOICES = [('CREATE','Create'),('UPDATE','Update'),('DELETE','Delete')]
    model_name   = models.CharField(max_length=100)
    object_id    = models.CharField(max_length=50)
    action       = models.CharField(max_length=10, choices=ACTION_CHOICES)
    changed_fields = models.JSONField(default=dict)
    changed_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    changed_at   = models.DateTimeField(auto_now_add=True)
    ip_address   = models.GenericIPAddressField(null=True, blank=True)
    notes        = models.TextField(blank=True)

    class Meta:
        ordering = ['-changed_at']


class TransactionEditLog(models.Model):
    """
    Track all edits to transactions (invoices, job cards, compliance deadlines).
    Allows superusers to modify transactions with full audit trail.
    """
    TRANSACTION_TYPES = [
        ('invoice', 'Invoice'),
        ('job_card', 'Job Card'),
        ('compliance_deadline', 'Compliance Deadline'),
        ('payment', 'Payment'),
    ]
    
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    transaction_id = models.IntegerField()
    transaction_code = models.CharField(max_length=50, blank=True)
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='transaction_edits')
    
    old_values = models.JSONField(default=dict)
    new_values = models.JSONField(default=dict)
    reason = models.TextField(blank=True)
    
    edited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transaction_edits')
    edited_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-edited_at']
        indexes = [
            models.Index(fields=['transaction_type', 'transaction_id']),
            models.Index(fields=['client', 'edited_at']),
        ]
    
    def __str__(self):
        return f"{self.get_transaction_type_display()} #{self.transaction_id} edited by {self.edited_by}"


class ReportingSettings(models.Model):
    """
    Configure reporting frequency and preferences.
    """
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly (Monday)'),
        ('biweekly', 'Bi-weekly'),
        ('monthly', 'Monthly (1st of month)'),
        ('quarterly', 'Quarterly'),
    ]
    
    REPORT_TYPES = [
        ('revenue', 'Revenue Report'),
        ('collections', 'Collections Report'),
        ('outstanding', 'Outstanding Invoices'),
        ('compliance', 'Compliance Status'),
        ('expenses', 'Expenses Report'),
        ('performance', 'Performance Summary'),
    ]
    
    name = models.CharField(max_length=200)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='reporting_settings')
    
    # Which reports to include
    report_types = models.JSONField(default=list, help_text="List of report types to generate")
    
    # Frequency settings
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    
    # Email recipients
    email_recipients = models.JSONField(default=list, help_text="List of emails to send reports to")
    
    # Threshold settings for alerts
    outstanding_threshold = models.DecimalField(max_digits=15, decimal_places=2, default=500000, 
                                               help_text="Alert if outstanding exceeds this amount")
    
    overdue_days_threshold = models.IntegerField(default=30,
                                                help_text="Alert if invoices overdue more than this many days")
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'Reporting Settings'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_frequency_display()})"


class DuplicateClientSuggestion(models.Model):
    """
    Track potential duplicate clients for review and action.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('confirmed', 'Confirmed Duplicate'),
        ('false_positive', 'False Positive'),
        ('merged', 'Merged'),
        ('dismissed', 'Dismissed'),
    ]
    
    primary_client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='duplicate_suggestions_as_primary')
    duplicate_client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='duplicate_suggestions_as_duplicate')
    
    similarity_score = models.IntegerField(help_text="Similarity percentage (0-100)")
    match_reasons = models.TextField(help_text="Reasons for duplicate suggestion")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_duplicates')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-similarity_score', '-created_at']
        unique_together = ('primary_client', 'duplicate_client')
    
    def __str__(self):
        return f"{self.primary_client.client_id} <-> {self.duplicate_client.client_id} ({self.similarity_score}%)"


class DuplicateTransactionAlert(models.Model):
    """
    Track potential duplicate transactions for review.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('confirmed', 'Confirmed Duplicate'),
        ('legitimate', 'Legitimate Transaction'),
        ('resolved', 'Resolved'),
    ]
    
    TRANSACTION_TYPES = [
        ('invoice', 'Invoice'),
        ('job_card', 'Job Card'),
        ('compliance_deadline', 'Compliance Deadline'),
    ]
    
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='duplicate_transaction_alerts')
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    transaction_id = models.IntegerField()
    
    potential_duplicates = models.JSONField(default=list, help_text="List of similar transaction IDs")
    reason = models.TextField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_transaction_type_display()} #{self.transaction_id} - {self.client}"


class MonthlyTrendData(models.Model):
    """
    Cache monthly aggregated data for dashboard trends.
    Improves dashboard performance with pre-calculated trend data.
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='monthly_trends')
    
    # Time period
    year = models.IntegerField()
    month = models.IntegerField()
    
    # Revenue metrics
    total_invoiced = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_collected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Expense metrics
    total_expenses = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Operations metrics
    jobs_created = models.IntegerField(default=0)
    jobs_completed = models.IntegerField(default=0)
    invoices_created = models.IntegerField(default=0)
    
    # Client metrics
    new_clients = models.IntegerField(default=0)
    
    # Calculated fields
    net_profit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    collection_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Percentage")
    
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-year', '-month']
        unique_together = ('company', 'year', 'month')
        indexes = [
            models.Index(fields=['company', 'year', 'month']),
        ]
    
    def __str__(self):
        return f"{self.year}-{self.month:02d} Trends"


class ModelVisibility(models.Model):
    """
    Admin-controlled per-model visibility switch.
    Stores a ContentType entry and whether that model is enabled (visible) to regular users.
    If no entry exists for a ContentType, visibility defaults to True.
    """
    content_type = models.OneToOneField(ContentType, on_delete=models.CASCADE, related_name='visibility')
    enabled = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True, help_text='Optional description for admin')

    class Meta:
        verbose_name = 'Model Visibility'
        verbose_name_plural = 'Model Visibilities'

    def __str__(self):
        return f"{self.content_type.app_label}.{self.content_type.model} - {'Enabled' if self.enabled else 'Disabled'}"


class UserModelPermission(models.Model):
    """
    Per-user per-model permission toggles.
    Admins can add entries to allow/deny viewing or editing of specific models for users.
    If no entry exists for a (user, model) pair, permissions fall back to global ModelVisibility
    and general staff status.
    """
    user = models.ForeignKey('core.User', on_delete=models.CASCADE, related_name='model_permissions')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name='user_permissions')
    can_view = models.BooleanField(default=True)
    can_edit = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ('user', 'content_type')
        verbose_name = 'User Model Permission'
        verbose_name_plural = 'User Model Permissions'

    def __str__(self):
        return f"{self.user} - {self.content_type.app_label}.{self.content_type.model} (view={self.can_view}, edit={self.can_edit})"
