from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from billing.models import Invoice, Payment
from services.models import JobCard, TimeEntry
from clients.models import Client
from compliance.models import ComplianceDeadline
from expenses.models import Expense
from notifications.models import NotificationLog
from credentials.models import ClientCredential
from core.automation import get_automation_status, get_automation_recommendations
from datetime import date


@login_required
def index(request):
    today = timezone.now().date()
    this_month = today.replace(day=1)
    seven_days = today + timezone.timedelta(days=7)

    # ── Revenue KPIs ──
    invoiced_month  = Invoice.objects.filter(date_issued__gte=this_month).aggregate(s=Sum('grand_total'))['s'] or 0
    collected_month = Payment.objects.filter(payment_date__gte=this_month).aggregate(s=Sum('amount'))['s'] or 0
    unpaid_qs       = Invoice.objects.exclude(status__in=['paid', 'written_off'])
    total_outstanding = (unpaid_qs.aggregate(s=Sum('grand_total'))['s'] or 0) - \
                        (unpaid_qs.aggregate(s=Sum('amount_paid'))['s'] or 0)
    jobs_completed  = JobCard.objects.filter(status='completed', completed_at__gte=this_month).count()

    # ── Expenses this month ──
    expenses_month     = Expense.objects.filter(expense_date__gte=this_month)
    total_expenses_month = expenses_month.aggregate(s=Sum('amount'))['s'] or 0
    expenses_by_cat    = (expenses_month.values('category__name')
                          .annotate(total=Sum('amount')).order_by('-total')[:6])

    # ── Net profit this month ──
    net_profit_month = float(collected_month) - float(total_expenses_month)

    # ── 6-month trend: revenue, collections, expenses ──
    rev_labels, rev_invoiced, rev_collected, rev_expenses = [], [], [], []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12; y -= 1
        rev_labels.append(date(y, m, 1).strftime('%b %Y'))
        mo_inv = Invoice.objects.filter(date_issued__year=y, date_issued__month=m).aggregate(s=Sum('grand_total'))['s'] or 0
        mo_col = Payment.objects.filter(payment_date__year=y, payment_date__month=m).aggregate(s=Sum('amount'))['s'] or 0
        mo_exp = Expense.objects.filter(expense_date__year=y, expense_date__month=m).aggregate(s=Sum('amount'))['s'] or 0
        rev_invoiced.append(float(mo_inv))
        rev_collected.append(float(mo_col))
        rev_expenses.append(float(mo_exp))

    # ── Job card counts ──
    job_counts = {s: JobCard.objects.filter(status=s).count() for s, _ in JobCard.STATUS}

    # ── Invoice aging ──
    aging = {'Current': 0, '1–30 days': 0, '31–60 days': 0, '61–90 days': 0, '90+ days': 0}
    for inv in Invoice.objects.exclude(status__in=['paid', 'written_off']):
        aging[inv.aging_bucket()] = aging.get(inv.aging_bucket(), 0) + float(inv.balance_due)

    # ── Upcoming deadlines ──
    upcoming_deadlines = ComplianceDeadline.objects.filter(
        status='upcoming', due_date__lte=seven_days
    ).select_related('obligation__client', 'obligation__service_type').order_by('due_date')

    # ── Top overdue invoices ──
    top_overdue = Invoice.objects.exclude(status__in=['paid', 'written_off']).order_by('-grand_total')[:10]

    # ── Suspended clients ──
    suspended_clients = Client.objects.filter(status='suspended').select_related('assigned_officer')[:10]

    # ── Credential alerts ──
    cred_alerts = ClientCredential.objects.filter(
        Q(status='needs_reset') | Q(expiry_date__lte=today + timezone.timedelta(days=14))
    ).select_related('client')[:10]

    # ── Staff performance ──
    from core.models import User
    staff_perf = []
    for u in User.objects.filter(is_active_staff=True, is_active=True):
        hours = TimeEntry.objects.filter(
            staff=u, entry_date__gte=this_month
        ).aggregate(h=Sum('hours'))['h'] or 0
        revenue = Invoice.objects.filter(
            job_card__assigned_to=u, date_issued__gte=this_month
        ).aggregate(s=Sum('grand_total'))['s'] or 0
        staff_perf.append({
            'user': u,
            'assigned':  JobCard.objects.filter(assigned_to=u).count(),
            'completed': JobCard.objects.filter(assigned_to=u, status='completed', completed_at__gte=this_month).count(),
            'overdue':   JobCard.objects.filter(assigned_to=u, status__in=['open', 'in_progress'], due_date__lt=today).count(),
            'hours':     round(float(hours), 1),
            'revenue':   float(revenue),
        })

    # ── Top clients by revenue this month ──
    top_clients = (Client.objects
        .filter(invoices__date_issued__gte=this_month)
        .annotate(revenue=Sum('invoices__grand_total'))
        .order_by('-revenue')[:5])

    # ── Pending expenses awaiting approval ──
    pending_expenses = Expense.objects.filter(status='submitted').select_related('category', 'paid_by')[:8]

    # ── Automation ──
    automation_status          = get_automation_status()
    automation_recommendations = get_automation_recommendations()
    recent_notifications       = NotificationLog.objects.order_by('-created_at')[:5]

    ctx = {
        'invoiced_month': invoiced_month, 'collected_month': collected_month,
        'total_outstanding': total_outstanding, 'jobs_completed': jobs_completed,
        'collection_rate': round((float(collected_month) / float(invoiced_month) * 100), 1) if invoiced_month else 0,
        'total_expenses_month': total_expenses_month,
        'net_profit_month': net_profit_month,
        'expenses_by_cat': expenses_by_cat,
        'pending_expenses': pending_expenses,
        'job_counts': job_counts, 'aging': aging,
        'upcoming_deadlines': upcoming_deadlines,
        'top_overdue': top_overdue, 'suspended_clients': suspended_clients,
        'cred_alerts': cred_alerts, 'staff_perf': staff_perf,
        'top_clients': top_clients,
        'rev_labels': rev_labels, 'rev_invoiced': rev_invoiced,
        'rev_collected': rev_collected, 'rev_expenses': rev_expenses,
        'recent_notifications': recent_notifications,
        'automation_status': automation_status,
        'automation_recommendations': automation_recommendations,
        'today': today,
    }
    return render(request, 'dashboard/index.html', ctx)
