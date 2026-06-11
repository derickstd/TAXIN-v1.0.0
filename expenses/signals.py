"""Signals for automatic expense approval."""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Expense
from .utils import should_require_approval


@receiver(post_save, sender=Expense)
def auto_approve_expense_on_submit(sender, instance, created, update_fields, **kwargs):
    """
    Auto-approve expenses when submitted if they don't require approval.
    """
    # Only process if status was changed to 'submitted'
    if update_fields is None or 'status' in update_fields:
        if instance.status == 'submitted' and not should_require_approval(instance):
            # Auto-approve by updating status
            Expense.objects.filter(pk=instance.pk).update(status='approved')
