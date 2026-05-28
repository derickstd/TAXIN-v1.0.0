from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import TaxEvent
from .forms import TaxEventForm


@login_required
def calendar_view(request):
    today = timezone.now().date()
    events = TaxEvent.objects.select_related('assigned_to').all()
    status = request.GET.get('status', '')
    if status:
        events = events.filter(status=status)
    # Auto-mark overdue upcoming events
    TaxEvent.objects.filter(status='upcoming', due_date__lt=today).update(status='missed')
    return render(request, 'taxcalendar/calendar.html', {
        'events': events,
        'status': status,
        'status_choices': TaxEvent.STATUS,
        'today': today,
        'form': TaxEventForm(),
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
