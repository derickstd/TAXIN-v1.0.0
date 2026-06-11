"""
Reporting utilities for generating various reports based on settings.
"""

from django.utils import timezone
from django.db.models import Sum, Count, Q
from datetime import date, timedelta, datetime
from calendar import monthrange, month_name
from decimal import Decimal
import json

from billing.models import Invoice, Payment
from services.models import JobCard
from clients.models import Client
from compliance.models import ComplianceDeadline
from expenses.models import Expense
from core.models import MonthlyTrendData


def get_date_range_for_frequency(frequency, reference_date=None):
    """
    Get start and end dates based on reporting frequency.
    """
    if reference_date is None:
        reference_date = timezone.now().date()
    
    if frequency == 'daily':
        start = reference_date
        end = reference_date
    elif frequency == 'weekly':
        # Previous week (Monday to Sunday)
        days_back = reference_date.weekday() + 7  # Add 7 to get previous week
        start = reference_date - timedelta(days=days_back)
        end = start + timedelta(days=6)
    elif frequency == 'biweekly':
        # Previous 14 days
        start = reference_date - timedelta(days=14)
        end = reference_date
    elif frequency == 'monthly':
        # Previous month
        if reference_date.month == 1:
            first_day = reference_date.replace(year=reference_date.year - 1, month=12, day=1)
        else:
            first_day = reference_date.replace(month=reference_date.month - 1, day=1)
        
        last_day = date(first_day.year, first_day.month, monthrange(first_day.year, first_day.month)[1])
        start = first_day
        end = last_day
    elif frequency == 'quarterly':
        # Previous quarter
        quarter = (reference_date.month - 1) // 3
        if quarter == 0:
            quarter = 4
            year = reference_date.year - 1
        else:
            year = reference_date.year
        
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        end_month = quarter * 3
        last_day = monthrange(year, end_month)[1]
        end = date(year, end_month, last_day)
    else:
        start = reference_date
        end = reference_date
    
    return start, end


def calculate_monthly_trends(company, year, month):
    """
    Calculate and cache monthly trend data.
    """
    # Get month boundaries
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    
    # Revenue metrics
    invoiced = Invoice.objects.filter(
        date_issued__gte=first_day,
        date_issued__lte=last_day,
        client__company=company
    ).aggregate(total=Sum('grand_total'))['total'] or Decimal('0')
    
    collected = Payment.objects.filter(
        payment_date__gte=first_day,
        payment_date__lte=last_day,
        invoice__client__company=company
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    # Expense metrics
    expenses = Expense.objects.filter(
        expense_date__gte=first_day,
        expense_date__lte=last_day,
        company=company
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    # Operations metrics
    jobs_created = JobCard.objects.filter(
        created_at__gte=first_day,
        created_at__lte=last_day,
        client__company=company
    ).count()
    
    jobs_completed = JobCard.objects.filter(
        completed_at__gte=first_day,
        completed_at__lte=last_day,
        client__company=company,
        status='completed'
    ).count()
    
    invoices_created = Invoice.objects.filter(
        created_at__gte=first_day,
        created_at__lte=last_day,
        client__company=company
    ).count()
    
    # Client metrics
    new_clients = Client.objects.filter(
        created_at__gte=first_day,
        created_at__lte=last_day,
        company=company
    ).count()
    
    # Calculate derived metrics
    net_profit = float(collected) - float(expenses)
    collection_rate = (float(collected) / float(invoiced) * 100) if invoiced else Decimal('0')
    
    # Create or update trend data
    trend, created = MonthlyTrendData.objects.update_or_create(
        company=company,
        year=year,
        month=month,
        defaults={
            'total_invoiced': invoiced,
            'total_collected': collected,
            'total_expenses': expenses,
            'jobs_created': jobs_created,
            'jobs_completed': jobs_completed,
            'invoices_created': invoices_created,
            'new_clients': new_clients,
            'net_profit': net_profit,
            'collection_rate': collection_rate,
        }
    )
    
    return trend


def generate_revenue_report(company, start_date, end_date):
    """Generate revenue report for date range."""
    invoiced = Invoice.objects.filter(
        date_issued__gte=start_date,
        date_issued__lte=end_date,
        client__company=company
    ).aggregate(total=Sum('grand_total'))['total'] or Decimal('0')
    
    collected = Payment.objects.filter(
        payment_date__gte=start_date,
        payment_date__lte=end_date,
        invoice__client__company=company
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    # Top clients
    top_clients = Invoice.objects.filter(
        date_issued__gte=start_date,
        date_issued__lte=end_date,
        client__company=company
    ).values('client__full_name', 'client_id').annotate(
        total=Sum('grand_total')
    ).order_by('-total')[:10]
    
    return {
        'period': f"{start_date} to {end_date}",
        'total_invoiced': float(invoiced),
        'total_collected': float(collected),
        'outstanding': float(invoiced - collected),
        'collection_rate': (float(collected) / float(invoiced) * 100) if invoiced else 0,
        'top_clients': list(top_clients),
    }


def generate_collections_report(company, start_date, end_date):
    """Generate collections report."""
    payments = Payment.objects.filter(
        payment_date__gte=start_date,
        payment_date__lte=end_date,
        invoice__client__company=company
    )
    
    total_collected = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    payment_methods = payments.values('invoice__payment_method').annotate(
        total=Sum('amount')
    ).order_by('-total')
    
    return {
        'period': f"{start_date} to {end_date}",
        'total_collected': float(total_collected),
        'payment_methods': list(payment_methods),
        'payment_count': payments.count(),
        'average_payment': float(total_collected / payments.count()) if payments.count() > 0 else 0,
    }


def generate_outstanding_report(company):
    """Generate outstanding invoices report."""
    outstanding = Invoice.objects.filter(
        client__company=company,
        status__in=['sent', 'partially_paid', 'overdue']
    ).exclude(balance_due=0)
    
    total_outstanding = outstanding.aggregate(
        total=Sum('grand_total') - Sum('amount_paid')
    )['total'] or Decimal('0')
    
    # Categorize by age
    today = timezone.now().date()
    
    current = outstanding.filter(due_date__gte=today).count()
    overdue_7 = outstanding.filter(due_date__lt=today, due_date__gte=today - timedelta(days=7)).count()
    overdue_30 = outstanding.filter(due_date__lt=today - timedelta(days=7), due_date__gte=today - timedelta(days=30)).count()
    overdue_90 = outstanding.filter(due_date__lt=today - timedelta(days=30)).count()
    
    return {
        'total_outstanding': float(total_outstanding),
        'invoice_count': outstanding.count(),
        'by_age': {
            'current': current,
            'overdue_7': overdue_7,
            'overdue_30': overdue_30,
            'overdue_90': overdue_90,
        },
        'top_outstanding_clients': list(
            outstanding.values('client__full_name', 'client_id').annotate(
                amount=Sum('grand_total') - Sum('amount_paid')
            ).order_by('-amount')[:10]
        )
    }


def generate_compliance_report(company):
    """Generate compliance deadline status report."""
    from compliance.models import ComplianceObligation
    
    today = timezone.now().date()
    
    deadlines = ComplianceDeadline.objects.filter(
        obligation__client__company=company
    )
    
    upcoming = deadlines.filter(status='upcoming', due_date__gte=today).count()
    overdue = deadlines.filter(status='upcoming', due_date__lt=today).count()
    filed_not_paid = deadlines.filter(status='filed_not_paid').count()
    paid_not_filed = deadlines.filter(status='paid_not_filed').count()
    
    # Upcoming deadlines (next 30 days)
    upcoming_deadlines = deadlines.filter(
        status='upcoming',
        due_date__gte=today,
        due_date__lte=today + timedelta(days=30)
    ).select_related('obligation__client', 'obligation__service_type').order_by('due_date')[:20]
    
    return {
        'total_deadlines': deadlines.count(),
        'status': {
            'upcoming': upcoming,
            'overdue': overdue,
            'filed_not_paid': filed_not_paid,
            'paid_not_filed': paid_not_filed,
        },
        'upcoming_deadlines': [
            {
                'client': d.obligation.client.full_name,
                'service': d.obligation.service_type.name,
                'period': d.period_label,
                'due_date': str(d.due_date),
                'days_until': (d.due_date - today).days,
            }
            for d in upcoming_deadlines
        ]
    }


def generate_expenses_report(company, start_date, end_date):
    """Generate expenses report."""
    from expenses.models import ExpenseCategory
    
    expenses = Expense.objects.filter(
        expense_date__gte=start_date,
        expense_date__lte=end_date,
        company=company
    )
    
    total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    by_category = expenses.values('category__name').annotate(
        total=Sum('amount')
    ).order_by('-total')
    
    return {
        'period': f"{start_date} to {end_date}",
        'total_expenses': float(total_expenses),
        'by_category': list(by_category),
        'expense_count': expenses.count(),
    }


def generate_performance_summary(company, start_date, end_date):
    """Generate overall performance summary."""
    # Get all metrics
    revenue_report = generate_revenue_report(company, start_date, end_date)
    collections_report = generate_collections_report(company, start_date, end_date)
    outstanding_report = generate_outstanding_report(company)
    expenses_report = generate_expenses_report(company, start_date, end_date)
    
    collected = collections_report['total_collected']
    expenses = expenses_report['total_expenses']
    net_profit = collected - expenses
    
    return {
        'period': f"{start_date} to {end_date}",
        'revenue': revenue_report['total_invoiced'],
        'collected': collected,
        'outstanding': outstanding_report['total_outstanding'],
        'expenses': expenses,
        'net_profit': net_profit,
        'collection_rate': revenue_report['collection_rate'],
    }
