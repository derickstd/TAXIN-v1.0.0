from django.db import models
from core.models import User


class TaxEvent(models.Model):
    EVENT_TYPE = [
        ('ura_filing', 'URA Filing Deadline'),
        ('nssf', 'NSSF Deadline'),
        ('ursb', 'URSB Deadline'),
        ('payment', 'Tax Payment Due'),
        ('internal', 'Internal Deadline'),
        ('reminder', 'Reminder'),
        ('other', 'Other'),
    ]
    STATUS = [
        ('upcoming', 'Upcoming'),
        ('done', 'Done'),
        ('missed', 'Missed'),
        ('cancelled', 'Cancelled'),
    ]

    title = models.CharField(max_length=300)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE, default='internal')
    due_date = models.DateField()
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='upcoming')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tax_events')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_tax_events')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date']

    def __str__(self):
        return f"{self.title} — {self.due_date}"
