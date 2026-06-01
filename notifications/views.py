from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Max

from .models import NotificationLog, MessageThread, Message
from .forms import NewMessageForm, ReplyMessageForm
from .services import send_debt_reminders, send_manager_debt_report

@login_required
def notification_list(request):
    logs = NotificationLog.objects.select_related('client','triggered_by').all()[:200]
    return render(request, 'notifications/log_list.html', {'logs': logs})

@login_required
def message_threads(request):
    threads = list(MessageThread.objects
               .filter(participants=request.user)
               .annotate(last_activity=Max('messages__created_at'))
               .order_by('-last_activity', '-created_at'))
    for thread in threads:
        thread.unread_count_for_user = thread.messages.exclude(read_by=request.user).count()
    return render(request, 'notifications/message_threads.html', {
        'threads': threads,
    })

@login_required
def message_new(request):
    if request.method == 'POST':
        form = NewMessageForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            recipients = form.cleaned_data['recipients']
            subject = form.cleaned_data['subject']
            body = form.cleaned_data['body']
            attachment = form.cleaned_data.get('attachment')
            thread = MessageThread.objects.create(subject=subject, created_by=request.user)
            thread.participants.set(list(recipients) + [request.user])
            message = Message.objects.create(
                thread=thread,
                sender=request.user,
                body=body,
                attachment=attachment,
            )
            message.read_by.add(request.user)
            return redirect('notifications:message_thread', thread_id=thread.id)
    else:
        form = NewMessageForm(user=request.user)
    return render(request, 'notifications/message_new.html', {'form': form})

@login_required
def message_thread_detail(request, thread_id):
    thread = get_object_or_404(MessageThread, pk=thread_id, participants=request.user)
    thread_messages = thread.messages.select_related('sender').all()
    unread_messages = thread_messages.exclude(read_by=request.user)
    for msg in unread_messages:
        msg.read_by.add(request.user)
    form = ReplyMessageForm()
    return render(request, 'notifications/message_thread_detail.html', {
        'thread': thread,
        'messages': thread_messages,
        'form': form,
    })

@login_required
def message_reply(request, thread_id):
    thread = get_object_or_404(MessageThread, pk=thread_id, participants=request.user)
    if request.method == 'POST':
        form = ReplyMessageForm(request.POST, request.FILES)
        if form.is_valid():
            body = form.cleaned_data['body']
            attachment = form.cleaned_data.get('attachment')
            message = Message.objects.create(
                thread=thread,
                sender=request.user,
                body=body,
                attachment=attachment,
            )
            message.read_by.add(request.user)
            return redirect('notifications:message_thread', thread_id=thread.id)
    return redirect('notifications:message_thread', thread_id=thread.id)

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
