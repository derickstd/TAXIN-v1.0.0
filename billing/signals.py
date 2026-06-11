from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from decimal import Decimal
from billing.models import Invoice, Payment


def recalc_client_outstanding(client):
    """
    Sum of (grand_total - amount_paid) for every unpaid invoice.
    This is the single correct formula — never mixes different sets.
    """
    unpaid = Invoice.objects.filter(
        client=client
    ).exclude(status__in=['paid', 'written_off'])

    balance = sum(
        max(Decimal('0'), inv.grand_total - inv.amount_paid)
        for inv in unpaid
    )

    if client.total_outstanding != balance:
        client.total_outstanding = balance
        client.save(update_fields=['total_outstanding'])


# Alias kept for any existing callers
update_client_outstanding = recalc_client_outstanding


def _sync_invoice_after_payment(invoice):
    """
    Recalculate amount_paid from actual Payment records (source of truth),
    cap it at grand_total so balance_due never goes negative,
    then update status. If fully paid, cascade to job card.
    """
    total_paid = sum(p.amount for p in invoice.payments.all())
    total_paid = min(total_paid, invoice.grand_total)
    total_paid = max(Decimal('0'), total_paid)

    Invoice.objects.filter(pk=invoice.pk).update(amount_paid=total_paid)
    invoice.amount_paid = total_paid
    invoice.update_status()

    # Cascade to job card when invoice is fully settled
    if invoice.amount_paid >= invoice.grand_total and invoice.grand_total > 0:
        _settle_job_card(invoice)


def _settle_job_card(invoice):
    """Mark all job card line items as handled_paid and complete the job card."""
    from django.utils import timezone as tz
    job = getattr(invoice, 'job_card', None)
    if job is None:
        try:
            job = invoice.job_card
        except Exception:
            return
    if job is None:
        return
    # Mark any handled items as paid, but preserve unpaid or unhandled work.
    job.line_items.filter(status='handled_not_paid').update(status='handled_paid')
    # Do not auto-complete if there is still unhandled work.
    if job.line_items.filter(status__in=['not_handled', 'paid_not_handled']).exists():
        return
    # Complete the job card if not already
    if job.status != 'completed':
        job.status = 'completed'
        job.completed_at = tz.now()
        job.save(update_fields=['status', 'completed_at'])
        from services.models import StaffActivityLog, TimeEntry
        StaffActivityLog.objects.create(
            job_card=job,
            staff=None,
            action='Job card auto-completed — invoice fully paid',
        )
        TimeEntry.objects.create(
            job_card=job,
            staff=None,
            description='Invoice settled — job marked complete',
            hours=Decimal('0.25'),
            entry_date=tz.now().date(),
        )


@receiver(post_save, sender=Payment)
def on_payment_saved(sender, instance, created, **kwargs):
    if not created:
        return
    invoice = instance.invoice
    # Reload grand_total fresh — services signal may have updated it
    invoice.refresh_from_db(fields=['grand_total', 'amount_paid'])
    _sync_invoice_after_payment(invoice)
    if invoice.client:
        from django.utils import timezone
        invoice.client.last_transaction_date = timezone.now().date()
        invoice.client.save(update_fields=['last_transaction_date'])
        recalc_client_outstanding(invoice.client)


@receiver(post_delete, sender=Payment)
def on_payment_deleted(sender, instance, **kwargs):
    invoice = instance.invoice
    invoice.refresh_from_db(fields=['grand_total', 'amount_paid'])
    _sync_invoice_after_payment(invoice)
    if invoice.client:
        recalc_client_outstanding(invoice.client)


@receiver(post_delete, sender=Invoice)
def on_invoice_deleted(sender, instance, **kwargs):
    if instance.client:
        recalc_client_outstanding(instance.client)
