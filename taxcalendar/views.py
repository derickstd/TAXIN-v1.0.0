from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import TaxEvent
from .forms import TaxEventForm
from django.db.models import Sum
import calendar as _calendar
from datetime import date
from billing.models import Payment
from expenses.models import Expense


@login_required
def calendar_view(request):
    today = timezone.now().date()
    events = TaxEvent.objects.select_related('assigned_to').all()
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
            day_payments = Payment.objects.filter(payment_date=filter_day).order_by('-payment_date')
            day_expenses = Expense.objects.filter(expense_date=filter_day).order_by('-expense_date')
        except Exception:
            filter_day = None
    if status:
        events = events.filter(status=status)
    # Auto-mark overdue upcoming events
    TaxEvent.objects.filter(status='upcoming', due_date__lt=today).update(status='missed')
    # Financial summary: money in (payments) and money out (approved expenses) for each day of current month
    year = today.year
    month = today.month
    _, days_in_month = _calendar.monthrange(year, month)
    month_days = [date(year, month, d) for d in range(1, days_in_month + 1)]
    daily_summaries = {}
    daily_list = []
    for d in month_days:
        money_in = Payment.objects.filter(payment_date=d).aggregate(total=Sum('amount'))['total'] or 0
        money_out = Expense.objects.filter(expense_date=d, status='approved').aggregate(total=Sum('amount'))['total'] or 0
        daily_summaries[d] = {'money_in': money_in, 'money_out': money_out}
        daily_list.append((d, money_in, money_out))
    # Build calendar grid (weeks) for month view and attach events to each day
    month_calendar = _calendar.monthcalendar(year, month)
    events_in_month = events.filter(due_date__year=year, due_date__month=month)
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
                week_days.append({'day': day, 'date': dobj, 'events': events_by_date.get(dobj, [])})
        month_weeks.append(week_days)
    return render(request, 'taxcalendar/calendar.html', {
        'events': events,
        'status': status,
        'status_choices': TaxEvent.STATUS,
        'today': today,
        'form': TaxEventForm(),
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
        form = TaxEventForm(request.POST)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.created_by = request.user
            ev.save()
            messages.success(request, f'Event "{ev.title}" added to tax calendar.')
            return redirect('taxcalendar:list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, 'taxcalendar/calendar.html', {
            'events': TaxEvent.objects.all(),
            'form': form,
            'open_modal': True,
            'status_choices': TaxEvent.STATUS,
            'today': timezone.now().date(),
        })
    return redirect('taxcalendar:list')


@login_required
def event_update_status(request, pk):
    ev = get_object_or_404(TaxEvent, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(TaxEvent.STATUS):
            ev.status = new_status
            ev.save(update_fields=['status'])
    return redirect('taxcalendar:list')


@login_required
def event_delete(request, pk):
    ev = get_object_or_404(TaxEvent, pk=pk)
    if request.method == 'POST':
        ev.delete()
        messages.success(request, 'Event deleted.')
    return redirect('taxcalendar:list')
