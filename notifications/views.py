from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import NotificationLog
from .services import send_debt_reminders, send_manager_debt_report

@login_required
def notification_list(request):
    logs = NotificationLog.objects.select_related('client','triggered_by').all()[:200]
    return render(request, 'notifications/log_list.html', {'logs': logs})

@login_required
def send_reminders_now(request):
    if request.method == 'POST':
        result = send_debt_reminders()
        if isinstance(result, dict):
            messages.success(request, f'Debt reminders sent: {result["whatsapp"]} WhatsApp, {result["email"]} Email.')
        else:
            messages.success(request, 'Debt reminders sent (or queued).')
    return redirect('notifications:list')

@login_required
def send_manager_report_now(request):
    if request.method == 'POST':
        send_manager_debt_report()
        messages.success(request, 'Manager debt report sent.')
    return redirect('notifications:list')


@login_required
def send_task_reminders_now(request):
    if request.method == 'POST':
        from notifications.services import send_incomplete_task_reminders
        send_incomplete_task_reminders()
        messages.success(request, 'Task reminders sent to all staff.')
    return redirect('notifications:list')
