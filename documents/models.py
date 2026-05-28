from django.db import models
from clients.models import Client
from services.models import JobCard
from core.models import User


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
