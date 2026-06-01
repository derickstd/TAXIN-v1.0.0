from django.db import models
from clients.models import Client
from core.models import User

class NotificationLog(models.Model):
    TYPE = [
        ('debt_reminder','Debt Reminder'),('invoice_delivery','Invoice Delivery'),
        ('deadline_alert','Deadline Alert'),('internal_alert','Internal Manager Alert'),
        ('payment_confirmation','Payment Confirmation'),
    ]
    STATUS = [('queued','Queued'),('sent','Sent'),('delivered','Delivered'),('failed','Failed')]
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    recipient_number = models.CharField(max_length=30)
    message_type = models.CharField(max_length=30, choices=TYPE)
    message_body = models.TextField()
    attachment_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='queued')
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    triggered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_message_type_display()} to {self.recipient_number} — {self.status}"


class MessageThread(models.Model):
    subject = models.CharField(max_length=120, blank=True)
    participants = models.ManyToManyField(User, related_name='message_threads')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='started_message_threads')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.subject or f"Thread #{self.pk}"

    def last_message(self):
        return self.messages.order_by('-created_at').first()

    def unread_count(self, user):
        return self.messages.exclude(read_by=user).count()


class Message(models.Model):
    thread = models.ForeignKey(MessageThread, related_name='messages', on_delete=models.CASCADE)
    sender = models.ForeignKey(User, related_name='sent_messages', on_delete=models.SET_NULL, null=True, blank=True)
    body = models.TextField()
    attachment = models.FileField(upload_to='message_attachments/%Y/%m/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_by = models.ManyToManyField(User, related_name='read_messages', blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message from {self.sender} in {self.thread}"
