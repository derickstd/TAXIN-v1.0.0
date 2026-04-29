from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal
from .models import JobCard, JobCardLineItem
from billing.models import Invoice, Payment
from clients.models import Client


@receiver(post_save, sender=JobCardLineItem)
def auto_update_jobcard_on_line_item_change(sender, instance, created, **kwargs):
    """
    Automatically update job card total and status when line items change
    """
    job = instance.job_card
    job.update_total()
    
    # Auto-update job status based on line item statuses
    all_items = list(job.line_items.all())
    if not all_items:
        return
    
    all_paid = all(li.status == 'handled_paid' for li in all_items)
    all_handled = all(li.status in ('handled_paid', 'handled_not_paid') for li in all_items)
    any_handled = any(li.status in ('handled_paid', 'handled_not_paid') for li in all_items)
    
    # Auto-update job card status
    if all_paid and job.status != 'completed':
        job.status = 'completed'
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])
    elif all_handled and job.status not in ('completed', 'pending_payment'):
        job.status = 'pending_payment'
        job.save(update_fields=['status'])
    elif any_handled and job.status == 'open':
        job.status = 'in_progress'
        job.save(update_fields=['status'])
    
    # Auto-update invoice if exists
    if hasattr(job, 'invoice'):
        auto_sync_invoice_with_jobcard(job)


@receiver(post_save, sender=Payment)
def auto_update_invoice_and_client_on_payment(sender, instance, created, **kwargs):
    """
    Automatically update invoice status and client outstanding when payment is recorded
    """
    if not created:
        return
    
    invoice = instance.invoice
    invoice.amount_paid = sum(p.amount for p in invoice.payments.all())
    invoice.update_status()
    
    # Update client outstanding balance
    client = invoice.client
    from django.db.models import Sum, Q
    total_outstanding = Invoice.objects.filter(
        client=client,
        status__in=['sent', 'partially_paid', 'overdue']
    ).aggregate(total=Sum('grand_total'))['total'] or Decimal('0')
    
    total_paid = Invoice.objects.filter(
        client=client
    ).aggregate(paid=Sum('amount_paid'))['paid'] or Decimal('0')
    
    client.total_outstanding = max(Decimal('0'), total_outstanding - total_paid)
    client.last_transaction_date = timezone.now().date()
    client.save(update_fields=['total_outstanding', 'last_transaction_date'])
    
    # Auto-update job card line items to "handled_paid" if invoice is fully paid
    if invoice.status == 'paid' and invoice.job_card:
        job = invoice.job_card
        for line_item in job.line_items.filter(status='handled_not_paid'):
            line_item.status = 'handled_paid'
            line_item.save(update_fields=['status'])


@receiver(pre_save, sender=Client)
def auto_update_client_status(sender, instance, **kwargs):
    """
    Automatically update client status based on outstanding balance and activity
    """
    if not instance.pk:
        return
    
    # Suspend clients with debt > 60 days overdue
    if instance.total_outstanding > 0:
        from django.db.models import Q
        overdue_invoices = Invoice.objects.filter(
            client=instance,
            status__in=['overdue', 'sent', 'partially_paid']
        ).filter(due_date__lt=timezone.now().date() - timezone.timedelta(days=60))
        
        if overdue_invoices.exists() and instance.status == 'active':
            instance.status = 'suspended'
    
    # Mark as dormant if no transactions in 6 months
    if instance.last_transaction_date:
        days_inactive = (timezone.now().date() - instance.last_transaction_date).days
        if days_inactive > 180 and instance.status == 'active':
            instance.status = 'dormant'


def auto_sync_invoice_with_jobcard(job):
    """
    Sync invoice amounts and status with job card line items
    """
    if not hasattr(job, 'invoice'):
        return
    
    invoice = job.invoice
    all_items = list(job.line_items.all())
    
    # Recalculate invoice totals
    subtotal = sum(li.negotiated_price for li in all_items)
    vat_total = sum(li.vat_amount for li in all_items)
    grand_total = subtotal + vat_total
    
    invoice.subtotal = subtotal
    invoice.vat_total = vat_total
    invoice.grand_total = grand_total
    
    # Update invoice status based on line items
    all_paid = all(li.status == 'handled_paid' for li in all_items)
    any_handled = any(li.status in ('handled_paid', 'handled_not_paid') for li in all_items)
    
    if all_paid:
        invoice.amount_paid = grand_total
        invoice.status = 'paid'
    elif any_handled and invoice.status == 'draft':
        invoice.status = 'sent'
    
    invoice.save(update_fields=['subtotal', 'vat_total', 'grand_total', 'amount_paid', 'status'])


@receiver(post_save, sender=Invoice)
def auto_update_overdue_status(sender, instance, **kwargs):
    """
    Automatically mark invoices as overdue when due date passes
    """
    if instance.status in ('sent', 'partially_paid'):
        if timezone.now().date() > instance.due_date and instance.balance_due > 0:
            Invoice.objects.filter(pk=instance.pk).update(status='overdue')
