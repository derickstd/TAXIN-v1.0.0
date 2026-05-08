from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum
from decimal import Decimal
from billing.models import Invoice, Payment


def update_client_outstanding(client):
    """Update the outstanding balance for a client"""
    out = Invoice.objects.filter(client=client).exclude(
        status__in=['paid', 'written_off']
    ).aggregate(s=Sum('grand_total'))['s'] or Decimal('0')
    
    paid_sum = Invoice.objects.filter(client=client).aggregate(
        s=Sum('amount_paid')
    )['s'] or Decimal('0')
    
    balance = max(Decimal('0'), out - paid_sum)
    
    if client.total_outstanding != balance:
        client.total_outstanding = balance
        client.save(update_fields=['total_outstanding'])


@receiver(post_save, sender=Invoice)
def invoice_saved(sender, instance, **kwargs):
    """Update client outstanding when invoice is saved"""
    if instance.client:
        update_client_outstanding(instance.client)


@receiver(post_delete, sender=Invoice)
def invoice_deleted(sender, instance, **kwargs):
    """Update client outstanding when invoice is deleted"""
    if instance.client:
        update_client_outstanding(instance.client)


@receiver(post_save, sender=Payment)
def payment_saved(sender, instance, **kwargs):
    """Update client outstanding when payment is saved"""
    if instance.invoice and instance.invoice.client:
        update_client_outstanding(instance.invoice.client)


@receiver(post_delete, sender=Payment)
def payment_deleted(sender, instance, **kwargs):
    """Update client outstanding when payment is deleted"""
    if instance.invoice and instance.invoice.client:
        update_client_outstanding(instance.invoice.client)
