from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from .models import TaxEvent
from .forms import TaxEventForm
from django.db.models import Sum
import calendar as _calendar
from datetime import date
from billing.models import OtherIncome, Payment
from expenses.models import Expense
from types import SimpleNamespace
from core.branch_access import (
    accessible_branches, get_entry_branch, has_company_wide_branch_access,
    scope_queryset,
)


def _event_queryset(user):
    events = TaxEvent.objects.all()
    if user.is_superuser or (not user.company_id and not user.branch_id):
        return events
    if user.company_id and has_company_wide_branch_access(user):
        return events.filter(
            Q(created_by__company_id=user.company_id)
            | Q(assigned_to__company_id=user.company_id)
        )
    branches = accessible_branches(user)
    return events.filter(
        Q(created_by__branch__in=branches)
        | Q(assigned_to__branch__in=branches)
    )


@login_required
def calendar_view(request):
    today = timezone.now().date()
    events = list(_event_queryset(request.user).select_related('assigned_to'))
    from compliance.models import ComplianceDeadline

    # Compliance deadlines are the system-generated tax records. Present them
    # alongside manually added calendar events instead of hiding them in a separate section.
    deadlines = scope_queryset(
        request.user,
        ComplianceDeadline.objects.select_related(
            'obligation__client', 'obligation__service_type', 'filed_by',
        ),
        branch_path='obligation__client__branch',
    )
    for deadline in deadlines:
        if deadline.status in ('filed_and_paid',):
            display_status = 'done'
        elif deadline.status in ('overdue', 'penalty_issued'):
            display_status = 'missed'
        elif deadline.status == 'waived':
            display_status = 'cancelled'
        else:
            display_status = 'upcoming'
        events.append(SimpleNamespace(
            title=f'{deadline.obligation.service_type.name} — {deadline.obligation.client.get_display_name()}',
            event_type='ura_filing',
            due_date=deadline.due_date,
            description=deadline.period_label,
            status=display_status,
            assigned_to=deadline.filed_by,
            created_by=None,
            compliance_deadline=deadline,
        ))
    status = request.GET.get('status', '')
    # Optional: filter by a specific day to show payments/expenses on calendar detail
    day_param = request.GET.get('day')
    filter_day = None
    day_payments = []
    day_expenses = []
    if day_param:
        try:
            from datetime import datetime
            filter_day = datetime.strptime(day_param, '%Y-%m-%d').date()
            day_payments = scope_queryset(
                request.user, Payment.objects.filter(created_at__date=filter_day),
            ).order_by('-created_at')
            day_expenses = scope_queryset(
                request.user, Expense.objects.filter(created_at__date=filter_day),
            ).order_by('-created_at')
        except Exception:
            filter_day = None
    if status:
        events = [event for event in events if event.status == status]
    # Auto-mark overdue upcoming events
    _event_queryset(request.user).filter(
        status='upcoming', due_date__lt=today,
    ).update(status='missed')
    # Financial summary: money in (payments) and money out (approved expenses) for each day of current month
    year = today.year
    month = today.month
    _, days_in_month = _calendar.monthrange(year, month)
    month_days = [date(year, month, d) for d in range(1, days_in_month + 1)]
    daily_summaries = {}
    daily_list = []
    branch = get_entry_branch(request.user)
    for d in month_days:
        if branch and branch.external_reporting:
            from billing.models import BranchDailySummary
            summary = BranchDailySummary.objects.filter(branch=branch, business_date=d).first()
            money_in = summary.cash_inflow if summary else 0
            money_out = summary.cash_outflow if summary else 0
            transaction_count = 1 if summary else 0
        else:
            day_payments = scope_queryset(request.user, Payment.objects.filter(created_at__date=d))
            day_income = scope_queryset(request.user, OtherIncome.objects.filter(created_at__date=d))
            day_expenses = scope_queryset(request.user, Expense.objects.filter(created_at__date=d))
            payment_in = day_payments.aggregate(total=Sum('amount'))['total'] or 0
            other_income_in = day_income.aggregate(total=Sum('amount'))['total'] or 0
            money_in = payment_in + other_income_in
            money_out = day_expenses.aggregate(total=Sum('amount'))['total'] or 0
            transaction_count = day_payments.count() + day_income.count() + day_expenses.count()
        daily_summaries[d] = {
            'money_in': money_in,
            'money_out': money_out,
            'transaction_count': transaction_count,
        }
        daily_list.append((d, money_in, money_out))
    # Build calendar grid (weeks) for month view and attach events to each day
    month_calendar = _calendar.monthcalendar(year, month)
    events_in_month = [
        event for event in events
        if event.due_date.year == year and event.due_date.month == month
    ]
    events_by_date = {}
    for ev in events_in_month:
        events_by_date.setdefault(ev.due_date, []).append(ev)

    month_weeks = []
    for week in month_calendar:
        week_days = []
        for day in week:
            if day == 0:
                week_days.append({'day': 0, 'date': None, 'events': []})
            else:
                dobj = date(year, month, day)
                summary = daily_summaries[dobj]
                week_days.append({
                    'day': day,
                    'date': dobj,
                    'events': events_by_date.get(dobj, []),
                    'money_in': summary['money_in'],
                    'money_out': summary['money_out'],
                    'transaction_count': summary['transaction_count'],
                })
        month_weeks.append(week_days)
    return render(request, 'taxcalendar/calendar.html', {
        'events': events,
        'status': status,
        'status_choices': TaxEvent.STATUS,
        'today': today,
        'form': TaxEventForm(user=request.user),
        'month_days': month_days,
        'daily_summaries': daily_summaries,
        'daily_list': daily_list,
        'month_calendar': month_calendar,
        'month_weeks': month_weeks,
        'month': month,
        'year': year,
        'filter_day': filter_day,
        'day_payments': day_payments,
        'day_expenses': day_expenses,
    })


@login_required
def event_create(request):
    if request.method == 'POST':
        form = TaxEventForm(request.POST, user=request.user)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.created_by = request.user
            ev.save()
            messages.success(request, f'Event "{ev.title}" added to tax calendar.')
            return redirect('taxcalendar:list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, 'taxcalendar/calendar.html', {
            'events': _event_queryset(request.user),
            'form': form,
            'open_modal': True,
            'status_choices': TaxEvent.STATUS,
            'today': timezone.now().date(),
        })
    return redirect('taxcalendar:list')


@login_required
def event_update_status(request, pk):
    ev = get_object_or_404(
        _event_queryset(request.user),
        pk=pk,
    )
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(TaxEvent.STATUS):
            ev.status = new_status
            ev.save(update_fields=['status'])
    return redirect('taxcalendar:list')


@login_required
def event_delete(request, pk):
    ev = get_object_or_404(
        _event_queryset(request.user),
        pk=pk,
    )
    if request.method == 'POST':
        ev.delete()
        messages.success(request, 'Event deleted.')
    return redirect('taxcalendar:list')
