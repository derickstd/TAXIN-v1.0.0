from django.shortcuts import render
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from billing.models import Invoice, Payment, OtherIncome
from services.models import JobCard, TimeEntry
from clients.models import Client
from compliance.models import ComplianceDeadline
from expenses.models import Expense
from notifications.models import NotificationLog
from credentials.models import ClientCredential
from core.automation import get_automation_status, get_automation_recommendations
from core.reporting import calculate_monthly_trends
from datetime import date
import calendar as _calendar


@login_required
def index(request):
    today = timezone.now().date()
    this_month = today.replace(day=1)
    last_month = (this_month - timezone.timedelta(days=1)).replace(day=1)
    last_month_end = this_month - timezone.timedelta(days=1)
    seven_days = today + timezone.timedelta(days=7)

    period = request.GET.get('period', '30d')
    period_options = [
        ('7d', 'Last 7 days'),
        ('30d', 'Last 30 days'),
        ('2w', 'Last 2 weeks'),
        ('4w', 'Last 4 weeks'),
        ('3m', 'Last 3 months'),
        ('6m', 'Last 6 months'),
        ('12m', 'Last 12 months'),
    ]
    
    # Parse period and determine grouping
    if period == '7d':
        days_back = 7
        period_label = 'Last 7 days'
        group_by = 'day'
    elif period == '30d':
        days_back = 30
        period_label = 'Last 30 days'
        group_by = 'day'
    elif period == '2w':
        days_back = 14
        period_label = 'Last 2 weeks'
        group_by = 'week'
    elif period == '4w':
        days_back = 28
        period_label = 'Last 4 weeks'
        group_by = 'week'
    elif period == '3m':
        months = 3
        period_label = 'Last 3 months'
        group_by = 'month'
    elif period == '12m':
        months = 12
        period_label = 'Last 12 months'
        group_by = 'month'
    else:  # Default to 6 months
        months = 6
        period_label = 'Last 6 months'
        group_by = 'month'
    
    # For day/week grouping, set a default months value for calculations below
    if group_by != 'month':
        months = None

    def compare_metrics(current, previous):
        delta = current - previous
        if previous:
            pct = round((delta / previous) * 100, 1)
        elif current:
            pct = 100.0
        else:
            pct = 0
        if delta > 0:
            return pct, 'positive', f'Up {pct}% vs last month'
        if delta < 0:
            return abs(pct), 'negative', f'Down {abs(pct)}% vs last month'
        return pct, 'neutral', 'Flat vs last month'

    # ── Revenue KPIs ──
    invoiced_month  = Invoice.objects.filter(date_issued__gte=this_month).aggregate(s=Sum('grand_total'))['s'] or 0
    collected_month = Payment.objects.filter(payment_date__gte=this_month).aggregate(s=Sum('amount'))['s'] or 0
    other_income_month = OtherIncome.objects.filter(income_date__gte=this_month).aggregate(s=Sum('amount'))['s'] or 0
    total_income_month = float(collected_month) + float(other_income_month)
    unpaid_qs       = Invoice.objects.exclude(status__in=['paid', 'written_off'])
    total_outstanding = (unpaid_qs.aggregate(s=Sum('grand_total'))['s'] or 0) - \
                        (unpaid_qs.aggregate(s=Sum('amount_paid'))['s'] or 0)
    jobs_completed  = JobCard.objects.filter(status='completed', completed_at__gte=this_month).count()

    # ── Expenses this month ──
    expenses_month     = Expense.objects.filter(expense_date__gte=this_month)
    total_expenses_month = expenses_month.aggregate(s=Sum('amount'))['s'] or 0
    expenses_by_cat    = (expenses_month.values('category__name')
                          .annotate(total=Sum('amount')).order_by('-total')[:6])

    # ── Other income this month ──
    other_income_sources = OtherIncome.objects.filter(income_date__gte=this_month).order_by('-income_date')
    other_income_by_category = []
    for cat_choice, cat_name in OtherIncome.CATEGORY:
        cat_total = OtherIncome.objects.filter(income_date__gte=this_month, category=cat_choice).aggregate(s=Sum('amount'))['s'] or 0
        cat_count = OtherIncome.objects.filter(income_date__gte=this_month, category=cat_choice).count()
        if cat_total > 0:
            other_income_by_category.append((cat_name, float(cat_total), cat_count))
    other_income_by_category.sort(key=lambda x: x[1], reverse=True)

    # ── Net profit this month ──
    net_profit_month = total_income_month - float(total_expenses_month)
    collection_rate_month = round((float(collected_month) / float(invoiced_month) * 100), 1) if invoiced_month else 0
    new_clients_this_month = Client.objects.filter(created_at__gte=this_month).count()
    new_jobcards_this_month = JobCard.objects.filter(created_at__gte=this_month).count()
    notifications_this_month = NotificationLog.objects.filter(created_at__gte=this_month).count()

    invoiced_last_month = Invoice.objects.filter(date_issued__gte=last_month, date_issued__lte=last_month_end).aggregate(s=Sum('grand_total'))['s'] or 0
    collected_last_month = Payment.objects.filter(payment_date__gte=last_month, payment_date__lte=last_month_end).aggregate(s=Sum('amount'))['s'] or 0
    other_income_last_month = OtherIncome.objects.filter(income_date__gte=last_month, income_date__lte=last_month_end).aggregate(s=Sum('amount'))['s'] or 0
    total_income_last_month = float(collected_last_month) + float(other_income_last_month)
    expenses_last_month = Expense.objects.filter(expense_date__gte=last_month, expense_date__lte=last_month_end).aggregate(s=Sum('amount'))['s'] or 0
    net_profit_last_month = total_income_last_month - float(expenses_last_month)
    jobs_completed_last_month = JobCard.objects.filter(status='completed', completed_at__gte=last_month, completed_at__lte=last_month_end).count()
    new_clients_last_month = Client.objects.filter(created_at__gte=last_month, created_at__lte=last_month_end).count()
    new_jobcards_last_month = JobCard.objects.filter(created_at__gte=last_month, created_at__lte=last_month_end).count()

    # Collection rate for last month (percentage)
    collection_rate_last_month = round((float(collected_last_month) / float(invoiced_last_month) * 100), 1) if invoiced_last_month else 0

    invoiced_pct, invoiced_state, invoiced_label = compare_metrics(invoiced_month, invoiced_last_month)
    collected_pct, collected_state, collected_label = compare_metrics(collected_month, collected_last_month)
    profit_pct, profit_state, profit_label = compare_metrics(net_profit_month, net_profit_last_month)
    jobs_pct, jobs_state, jobs_label = compare_metrics(jobs_completed, jobs_completed_last_month)
    new_clients_pct, clients_state, clients_label = compare_metrics(new_clients_this_month, new_clients_last_month)
    new_jobcards_pct, jobcards_state, jobcards_label = compare_metrics(new_jobcards_this_month, new_jobcards_last_month)
    rate_pct, rate_state, rate_label = compare_metrics(collection_rate_month, collection_rate_last_month)

    performance_comparison = [
        {
            'label': 'Invoiced',
            'current': invoiced_month,
            'url': '/billing/?',
            'icon': 'fas fa-file-invoice-dollar',
            'subtitle': invoiced_label,
            'state': invoiced_state,
            'currency': 'UGX',
        },
        {
            'label': 'Collected',
            'current': collected_month,
            'url': '/billing/?status=paid',
            'icon': 'fas fa-wallet',
            'subtitle': collected_label,
            'state': collected_state,
            'currency': 'UGX',
        },
        {
            'label': 'Other Income',
            'current': other_income_month,
            'url': '/dashboard/#other-income',
            'icon': 'fas fa-gift',
            'subtitle': f"Total {float(other_income_month):,.0f}" if other_income_month else 'No other income recorded',
            'state': 'neutral',
            'currency': 'UGX',
        },
        {
            'label': 'Net Profit',
            'current': net_profit_month,
            'url': '/expenses/?',
            'icon': 'fas fa-chart-pie',
            'subtitle': profit_label,
            'state': profit_state,
            'currency': 'UGX',
        },
        {
            'label': 'Jobs Completed',
            'current': jobs_completed,
            'url': '/services/?status=completed',
            'icon': 'fas fa-check-circle',
            'subtitle': jobs_label,
            'state': jobs_state,
            'currency': '',
        },
        {
            'label': 'New Clients',
            'current': new_clients_this_month,
            'url': '/clients/?',
            'icon': 'fas fa-user-plus',
            'subtitle': clients_label,
            'state': clients_state,
            'currency': '',
        },
        {
            'label': 'New Job Cards',
            'current': new_jobcards_this_month,
            'url': '/services/?',
            'icon': 'fas fa-briefcase',
            'subtitle': jobcards_label,
            'state': jobcards_state,
            'currency': '',
        },
        {
            'label': 'Collection Rate',
            'current': collection_rate_month,
            'url': '/billing/aging',
            'icon': 'fas fa-percent',
            'subtitle': rate_label,
            'state': rate_state,
            'currency': '',
        },
    ]

    # ── trend: revenue, collections, expenses, net profit, collection rate over selected period ──
    rev_labels, rev_invoiced, rev_collected, rev_expenses = [], [], [], []
    rev_net_profit, rev_collection_rate = [], []
    
    if group_by == 'day':
        # Daily grouping for last N days
        from django.utils.dateparse import parse_date
        start_date = today - timezone.timedelta(days=days_back)
        for i in range(days_back + 1):
            current_date = start_date + timezone.timedelta(days=i)
            rev_labels.append(current_date.strftime('%b %d'))
            mo_inv = Invoice.objects.filter(date_issued=current_date).aggregate(s=Sum('grand_total'))['s'] or 0
            mo_col = Payment.objects.filter(payment_date=current_date).aggregate(s=Sum('amount'))['s'] or 0
            mo_exp = Expense.objects.filter(expense_date=current_date).aggregate(s=Sum('amount'))['s'] or 0
            rev_invoiced.append(float(mo_inv))
            rev_collected.append(float(mo_col))
            rev_expenses.append(float(mo_exp))
            rev_net_profit.append(float(mo_col) - float(mo_exp))
            rev_collection_rate.append(round((float(mo_col) / float(mo_inv) * 100), 1) if mo_inv else 0)
    
    elif group_by == 'week':
        # Weekly grouping
        from datetime import timedelta
        start_date = today - timezone.timedelta(days=days_back)
        weeks = []
        current_week_start = start_date - timedelta(days=start_date.weekday())
        while current_week_start <= today:
            week_end = current_week_start + timedelta(days=6)
            weeks.append((current_week_start, week_end))
            current_week_start += timedelta(days=7)
        
        for week_start, week_end in weeks:
            rev_labels.append(week_start.strftime('%b %d'))
            mo_inv = Invoice.objects.filter(date_issued__gte=week_start, date_issued__lte=week_end).aggregate(s=Sum('grand_total'))['s'] or 0
            mo_col = Payment.objects.filter(payment_date__gte=week_start, payment_date__lte=week_end).aggregate(s=Sum('amount'))['s'] or 0
            mo_exp = Expense.objects.filter(expense_date__gte=week_start, expense_date__lte=week_end).aggregate(s=Sum('amount'))['s'] or 0
            rev_invoiced.append(float(mo_inv))
            rev_collected.append(float(mo_col))
            rev_expenses.append(float(mo_exp))
            rev_net_profit.append(float(mo_col) - float(mo_exp))
            rev_collection_rate.append(round((float(mo_col) / float(mo_inv) * 100), 1) if mo_inv else 0)
    
    else:  # Monthly grouping
        for i in range(months - 1, -1, -1):
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
            rev_net_profit.append(float(mo_col) - float(mo_exp))
            rev_collection_rate.append(round((float(mo_col) / float(mo_inv) * 100), 1) if mo_inv else 0)

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

    # Sort staff performance by revenue (descending) to highlight top contributors
    staff_perf.sort(key=lambda x: x.get('revenue', 0), reverse=True)

    # ── Top clients by revenue this month ──
    top_clients = (Client.objects
        .filter(invoices__date_issued__gte=this_month)
        .annotate(revenue=Sum('invoices__grand_total'))
        .order_by('-revenue')[:5])

    # ── Pending expenses awaiting approval ──
    pending_expenses = Expense.objects.filter(status='submitted').select_related('category', 'paid_by')[:8]
    pending_expenses_count = Expense.objects.filter(status='submitted').count()

    # ── Automation ──
    automation_status          = get_automation_status()
    automation_recommendations = get_automation_recommendations()
    recent_notifications       = NotificationLog.objects.order_by('-created_at')[:5]

    top_overdue_count = Invoice.objects.exclude(status__in=['paid', 'written_off']).count()
    quick_stats = [
        {'label': 'Pending Approvals', 'value': pending_expenses_count, 'subtitle': 'Expenses awaiting review', 'icon': 'fas fa-receipt', 'url': '/expenses/?status=submitted', 'color': 'purple'},
        {'label': 'Overdue Invoices', 'value': top_overdue_count, 'subtitle': 'Largest unpaid invoices', 'icon': 'fas fa-exclamation-triangle', 'url': '/billing/aging', 'color': 'red'},
        {'label': 'Credential Alerts', 'value': cred_alerts.count(), 'subtitle': 'Expiring or reset needed', 'icon': 'fas fa-key', 'url': '/credentials/', 'color': 'gold'},
        {'label': 'Upcoming Deadlines', 'value': upcoming_deadlines.count(), 'subtitle': 'Due in next 7 days', 'icon': 'fas fa-calendar-alt', 'url': '/compliance/', 'color': 'green'},
        {'label': 'Notifications Sent', 'value': notifications_this_month, 'subtitle': 'This month', 'icon': 'fas fa-bell', 'url': '/notifications/', 'color': 'blue'},
    ]

    ctx = {
        'invoiced_month': invoiced_month, 'collected_month': collected_month,
        'other_income_month': other_income_month, 'total_income_month': total_income_month,
        'other_income_sources': other_income_sources, 'other_income_by_category': other_income_by_category,
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
        'rev_net_profit': rev_net_profit, 'rev_collection_rate': rev_collection_rate,
        'performance_comparison': performance_comparison,
        'quick_stats': quick_stats,
        'month_label': this_month.strftime('%b %Y'),
        'selected_period': period,
        'period_options': period_options,
        'period_label': period_label,
        'recent_notifications': recent_notifications,
        'automation_status': automation_status,
        'automation_recommendations': automation_recommendations,
        'today': today,
        # Compact calendar for dashboard (supports navigation via cal_year/cal_month and zoom)
        'cal_year': request.GET.get('cal_year', today.year),
        'cal_month': request.GET.get('cal_month', today.month),
        'cal_zoom': request.GET.get('cal_zoom', 'month'),
    }
    # prepare compact calendar data
    try:
        cy = int(ctx['cal_year'])
        cm = int(ctx['cal_month'])
    except Exception:
        cy = today.year; cm = today.month
    cz = ctx.get('cal_zoom', 'month')
    if cz == 'month':
        # Build calendar weeks (rows) for month grid display
        cal = _calendar.Calendar()  # Monday-first; change firstweekday if needed
        weeks = []
        for week in cal.monthdatescalendar(cy, cm):
            week_row = []
            for d in week:
                if d.month == cm:
                    mi = Payment.objects.filter(payment_date=d).aggregate(s=Sum('amount'))['s'] or 0
                    mo = Expense.objects.filter(expense_date=d, status='approved').aggregate(s=Sum('amount'))['s'] or 0
                    net = float(mi) - float(mo)
                    week_row.append({
                        'date': d,
                        'income': mi,
                        'expense': mo,
                        'net': net,
                        'status': 'positive' if net > 0 else 'negative' if net < 0 else 'neutral',
                        'has_data': bool(mi or mo),
                    })
                else:
                    week_row.append(None)
            weeks.append(week_row)
        ctx.update({'cal_weeks': weeks, 'cal_label': date(cy, cm, 1).strftime('%b %Y')})
    elif cz == 'months':
        # show months in year totals
        months = []
        for m in range(1, 13):
            mo_in = Payment.objects.filter(payment_date__year=cy, payment_date__month=m).aggregate(s=Sum('amount'))['s'] or 0
            mo_out = Expense.objects.filter(expense_date__year=cy, expense_date__month=m, status='approved').aggregate(s=Sum('amount'))['s'] or 0
            net = float(mo_in) - float(mo_out)
            months.append({
                'label': _calendar.month_abbr[m],
                'income': mo_in,
                'expense': mo_out,
                'net': net,
                'status': 'positive' if net > 0 else 'negative' if net < 0 else 'neutral',
                'has_data': bool(mo_in or mo_out),
            })
        ctx.update({'cal_months': months, 'cal_label': str(cy)})
    else:
        # years view: show last 5 years totals
        years = []
        for y in range(today.year - 4, today.year + 1):
            y_in = Payment.objects.filter(payment_date__year=y).aggregate(s=Sum('amount'))['s'] or 0
            y_out = Expense.objects.filter(expense_date__year=y, status='approved').aggregate(s=Sum('amount'))['s'] or 0
            years.append((y, y_in, y_out))
        ctx.update({'cal_years': years, 'cal_label': f"{today.year - 4}–{today.year}"})
    return render(request, 'dashboard/index.html', ctx)


@login_required
def day_transactions(request):
    day_str = request.GET.get('day')
    if not day_str:
        return JsonResponse({'error': 'Missing day parameter'}, status=400)

    try:
        day = date.fromisoformat(day_str)
    except ValueError:
        return JsonResponse({'error': 'Invalid day format'}, status=400)

    payments = (Payment.objects.filter(payment_date=day)
                .select_related('invoice')
                .order_by('-created_at'))
    expenses = (Expense.objects.filter(expense_date=day)
                .select_related('category')
                .order_by('-created_at'))
    other_income = (OtherIncome.objects.filter(income_date=day)
                    .order_by('-created_at'))

    total_payments = payments.aggregate(s=Sum('amount'))['s'] or 0
    total_expenses = expenses.aggregate(s=Sum('amount'))['s'] or 0
    total_other_income = other_income.aggregate(s=Sum('amount'))['s'] or 0
    net = float(total_payments + total_other_income) - float(total_expenses)

    html = render_to_string('dashboard/day_transactions_fragment.html', {
        'payments': payments,
        'expenses': expenses,
        'other_income': other_income,
        'total_payments': total_payments,
        'total_expenses': total_expenses,
        'total_other_income': total_other_income,
        'net': net,
        'filter_day': day,
    }, request=request)

    return JsonResponse({'html': html, 'day': day_str})
