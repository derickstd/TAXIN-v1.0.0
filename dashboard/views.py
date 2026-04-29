from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from billing.models import Invoice, Payment
from services.models import JobCard
from clients.models import Client
from compliance.models import ComplianceDeadline
from expenses.models import Expense
from notifications.models import NotificationLog
from credentials.models import ClientCredential
from core.automation import get_automation_status, get_automation_recommendations

@login_required
def index(request):
    today = timezone.now().date()
    this_month = today.replace(day=1)
    seven_days = today + timezone.timedelta(days=7)

    # KPI cards
    invoiced_month = Invoice.objects.filter(date_issued__gte=this_month).aggregate(s=Sum('grand_total'))['s'] or 0
    collected_month = Payment.objects.filter(payment_date__gte=this_month).aggregate(s=Sum('amount'))['s'] or 0
    total_outstanding = Invoice.objects.exclude(status__in=['paid','written_off']).aggregate(
        s=Sum('grand_total'))['s'] or 0
    paid_against = Invoice.objects.exclude(status__in=['paid','written_off']).aggregate(
        s=Sum('amount_paid'))['s'] or 0
    total_outstanding = (total_outstanding or 0) - (paid_against or 0)
    jobs_completed = JobCard.objects.filter(status='completed', completed_at__gte=this_month).count()

    # Job card counts by status
    job_counts = {s: JobCard.objects.filter(status=s).count() for s,_ in JobCard.STATUS}

    # Invoice aging
    all_unpaid = Invoice.objects.exclude(status__in=['paid','written_off'])
    aging = {'Current':0,'1–30 days':0,'31–60 days':0,'61–90 days':0,'90+ days':0}
    for inv in all_unpaid:
        aging[inv.aging_bucket()] = aging.get(inv.aging_bucket(),0) + float(inv.balance_due)

    # Upcoming deadlines
    upcoming_deadlines = ComplianceDeadline.objects.filter(
        status='upcoming', due_date__lte=seven_days
    ).select_related('obligation__client','obligation__service_type').order_by('due_date')

    # Top overdue invoices
    top_overdue = Invoice.objects.exclude(status__in=['paid','written_off']).order_by('-grand_total')[:10]

    # Suspended clients
    suspended_clients = Client.objects.filter(status='suspended').select_related('assigned_officer')[:10]

    # Credential alerts
    cred_alerts = ClientCredential.objects.filter(
        Q(status='needs_reset') | Q(expiry_date__lte=today + timezone.timedelta(days=14))
    ).select_related('client')[:10]

    # Staff performance
    from core.models import User
    staff_perf = []
    for u in User.objects.filter(is_active_staff=True, is_active=True):
        staff_perf.append({
            'user': u,
            'assigned': JobCard.objects.filter(assigned_to=u).count(),
            'completed': JobCard.objects.filter(assigned_to=u, status='completed', completed_at__gte=this_month).count(),
            'overdue': JobCard.objects.filter(assigned_to=u, status__in=['open','in_progress'], due_date__lt=today).count(),
        })

    # Revenue last 6 months for chart
    from datetime import date
    rev_labels, rev_invoiced, rev_collected = [], [], []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12; y -= 1
        rev_labels.append(date(y,m,1).strftime('%b %Y'))
        mo_start = date(y,m,1)
        mo_inv = Invoice.objects.filter(date_issued__year=y, date_issued__month=m).aggregate(s=Sum('grand_total'))['s'] or 0
        mo_col = Payment.objects.filter(payment_date__year=y, payment_date__month=m).aggregate(s=Sum('amount'))['s'] or 0
        rev_invoiced.append(float(mo_inv))
        rev_collected.append(float(mo_col))

    # Recent notifications
    recent_notifications = NotificationLog.objects.order_by('-created_at')[:5]
    
    # Automation status and recommendations
    automation_status = get_automation_status()
    automation_recommendations = get_automation_recommendations()

    ctx = {
        'invoiced_month': invoiced_month, 'collected_month': collected_month,
        'total_outstanding': total_outstanding, 'jobs_completed': jobs_completed,
        'collection_rate': round((collected_month/invoiced_month*100),1) if invoiced_month else 0,
        'job_counts': job_counts, 'aging': aging,
        'upcoming_deadlines': upcoming_deadlines,
        'top_overdue': top_overdue, 'suspended_clients': suspended_clients,
        'cred_alerts': cred_alerts, 'staff_perf': staff_perf,
        'rev_labels': rev_labels, 'rev_invoiced': rev_invoiced, 'rev_collected': rev_collected,
        'recent_notifications': recent_notifications,
        'automation_status': automation_status,
        'automation_recommendations': automation_recommendations,
        'today': today,
    }
    return render(request, 'dashboard/index.html', ctx)
