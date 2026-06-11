"""Utilities for expense approval logic and helpers."""

from django.db.models import Q
from .models import Expense, ExpenseApprovalSettings


def get_approval_settings():
    """Get the global ExpenseApprovalSettings object, creating defaults if needed."""
    settings, _ = ExpenseApprovalSettings.objects.get_or_create(pk=1)
    return settings


def should_require_approval(expense_or_category):
    """
    Determine if an expense requires approval.
    
    Returns True if:
    - The expense category has approval_required=True, AND
    - The expense amount does not fall under the auto_approve_under_amount threshold, AND
    - The category is not in the auto_approve_expense_categories list
    """
    from .models import ExpenseCategory
    
    # If it's an Expense instance, get the category
    if isinstance(expense_or_category, Expense):
        category = expense_or_category.category
        amount = expense_or_category.amount
    elif isinstance(expense_or_category, ExpenseCategory):
        category = expense_or_category
        amount = None
    else:
        return True  # Default to requiring approval
    
    if not category:
        return True
    
    # Category explicitly disables approval requirement
    if not category.approval_required:
        return False
    
    settings = get_approval_settings()
    
    # Check if category is in auto-approve list
    if category in settings.auto_approve_expense_categories.all():
        return False
    
    # Check if amount is under auto-approve threshold
    if amount is not None and settings.auto_approve_under_amount > 0:
        if amount < settings.auto_approve_under_amount:
            return False
    
    return True


def auto_approve_eligible_expenses():
    """
    Find and auto-approve expenses that meet the criteria.
    Returns count of expenses auto-approved.
    
    Useful for running as a periodic task.
    """
    settings = get_approval_settings()
    
    # Find submitted expenses that should be auto-approved
    eligible = Expense.objects.filter(
        status='submitted',
        category__approval_required=False
    ) | Expense.objects.filter(
        status='submitted',
        category__in=settings.auto_approve_expense_categories.all()
    )
    
    # If threshold is set, also include small amounts
    if settings.auto_approve_under_amount > 0:
        eligible = Expense.objects.filter(
            status='submitted',
            amount__lt=settings.auto_approve_under_amount
        ) | eligible
    
    # Remove duplicates and auto-approve
    eligible = eligible.distinct()
    approved_count = eligible.update(status='approved')
    
    return approved_count


def require_receipt(expense):
    """
    Determine if an expense requires a receipt upload.
    
    Returns True if the expense amount exceeds the threshold.
    """
    settings = get_approval_settings()
    if expense.amount >= settings.require_receipt_under_amount:
        return not expense.receipt_upload
    return False
