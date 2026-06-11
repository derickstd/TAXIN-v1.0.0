from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import JobCard, JobCardLineItem


@receiver(post_save, sender=JobCardLineItem)
def auto_update_jobcard_on_line_item_change(sender, instance, **kwargs):
    """
    When a line item is saved:
    - Recalculate job card total
    - Auto-advance job card status based on all line item statuses
    - Sync invoice totals only if no payments have been made yet
    """
    job = instance.job_card
    job.update_total()

    all_items = list(job.line_items.all())
    if not all_items:
        return

    all_paid    = all(li.status == 'handled_paid'                           for li in all_items)
    all_handled = all(li.status in ('handled_paid', 'handled_not_paid')      for li in all_items)
    any_progress = any(li.status in ('handled_paid', 'handled_not_paid', 'paid_not_handled') for li in all_items)

    if all_paid and job.status != 'completed':
        JobCard.objects.filter(pk=job.pk).update(status='completed', completed_at=timezone.now())
    elif all_handled and job.status not in ('completed', 'pending_payment'):
        JobCard.objects.filter(pk=job.pk).update(status='pending_payment')
    elif any_progress and job.status == 'open':
        JobCard.objects.filter(pk=job.pk).update(status='in_progress')

    # Only sync invoice totals when no payments exist yet — once a client has paid,
    # changing grand_total would make balance_due go negative
    if hasattr(job, 'invoice'):
        inv = job.invoice
        if not inv.payments.exists():
            _sync_invoice_totals(job, inv)


@receiver(post_save, sender=JobCard)
def auto_update_invoice_on_job_completion(sender, instance, **kwargs):
    """When a job card is completed, move its invoice from draft to sent."""
    if instance.status == 'completed' and hasattr(instance, 'invoice'):
        inv = instance.invoice
        if inv.status == 'draft':
            from billing.models import Invoice
            Invoice.objects.filter(pk=inv.pk).update(status='sent')


def _sync_invoice_totals(job, inv):
    """Recalculate invoice subtotal/vat/grand_total from current line items."""
    from billing.models import Invoice
    all_items = list(job.line_items.all())
    subtotal  = sum(li.negotiated_price for li in all_items)
    vat_total = sum(li.vat_amount       for li in all_items)
    grand     = subtotal + vat_total
    Invoice.objects.filter(pk=inv.pk).update(
        subtotal=subtotal,
        vat_total=vat_total,
        grand_total=grand,
    )
