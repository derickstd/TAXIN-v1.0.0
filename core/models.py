from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_CHOICES = [
        ('receptionist', 'Receptionist'),
        ('tax_officer',  'Tax Officer'),
        ('senior_officer','Senior Officer'),
        ('manager',      'Manager'),
        ('admin',        'Admin'),
    ]
    THEME_CHOICES = [
        ('classic',  'Classic Blue'),
        ('forest',   'Forest Ledger'),
        ('sunset',   'Sunset Copper'),
        ('midnight', 'Midnight Slate'),
        ('dark',     'Dark Mode'),
        ('ocean',    'Ocean Teal'),
        ('rose',     'Rose Gold'),
        ('charcoal', 'Charcoal Pro'),
        ('violet',   'Violet Dusk'),
        ('earth',    'Earth Brown'),
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
    ui_theme          = models.CharField(max_length=20, choices=THEME_CHOICES, default='classic')

    def is_manager_or_admin(self):
        return self.role in ('manager', 'admin')

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
