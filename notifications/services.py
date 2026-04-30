from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail
from .models import NotificationLog


def get_notify_contacts():
    """Return all users who should receive manager alerts."""
    from core.models import User
    contacts = []
    for u in User.objects.filter(receive_debt_alerts=True, is_active=True):
        wa = u.phone_whatsapp
        if wa:
            contacts.append({'number': wa, 'name': u.get_full_name() or u.username, 'user': u})
    # fallback to settings
    if not contacts and getattr(settings, 'MANAGER_WHATSAPP', ''):
        contacts.append({'number': settings.MANAGER_WHATSAPP, 'name': 'Manager', 'user': None})
    return contacts


def get_firm_sender():
    """Get the firm's WhatsApp/email from admin user or settings."""
    from core.models import User
    admin = User.objects.filter(role='admin', is_active=True).first()
    return {
        'whatsapp': (admin.phone_whatsapp if admin else '') or getattr(settings, 'MANAGER_WHATSAPP', '+256785230670'),
        'email': (admin.email_notify if admin else '') or getattr(settings, 'FIRM_EMAIL', 'taxissues.go@gmail.com'),
        'name': getattr(settings, 'FIRM_NAME', 'Taxman256'),
    }


def send_email_notification(to_email, subject, message, client=None, msg_type='debt_reminder', triggered_by=None):
    """Send email notification to client or staff."""
    if not to_email:
        return False
    
    log = NotificationLog.objects.create(
        client=client,
        recipient_number=to_email,  # Store email in recipient_number field
        message_type=msg_type,
        message_body=message,
        triggered_by=triggered_by,
        status='queued',
    )
    
    sender = get_firm_sender()
    from_email = sender['email']
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[to_email],
            fail_silently=False,
        )
        log.status = 'sent'
        log.sent_at = timezone.now()
        log.save()
        return True
    except Exception as e:
        log.status = 'failed'
        log.error_message = str(e)
        log.save()
        return False


def send_whatsapp_message(to_number, message, client=None, msg_type='debt_reminder',
                           triggered_by=None, attachment_url=''):
    log = NotificationLog.objects.create(
        client=client, recipient_number=to_number, message_type=msg_type,
        message_body=message, attachment_url=attachment_url,
        triggered_by=triggered_by, status='queued',
    )
    sender = get_firm_sender()
    try:
        sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
        if not sid or sid.startswith('ACxxx') or sid == 'ACdemo':
            log.status = 'sent'
            log.sent_at = timezone.now()
            log.error_message = f'Demo mode — from {sender["whatsapp"]} to {to_number}'
            log.save()
            return True
        from twilio.rest import Client as TC
        tc = TC(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        tc.messages.create(
            body=message,
            from_=settings.TWILIO_WHATSAPP_NUMBER,
            to=f'whatsapp:{to_number}',
        )
        log.status = 'sent'
        log.sent_at = timezone.now()
        log.save()
        return True
    except Exception as e:
        log.status = 'failed'
        log.error_message = str(e)
        log.save()
        return False


def send_debt_reminders():
    """Friday: send debt reminder to every client with outstanding balance via WhatsApp AND Email."""
    from billing.models import Invoice
    from clients.models import Client
    from django.db.models import Sum
    sender = get_firm_sender()
    clients_with_debt = Client.objects.filter(
        invoices__status__in=['overdue', 'partially_paid', 'sent']).distinct()
    sent_whatsapp = 0
    sent_email = 0
    
    for client in clients_with_debt:
        out = Invoice.objects.filter(client=client).exclude(status__in=['paid','written_off']).aggregate(s=Sum('grand_total'))['s'] or 0
        paid = Invoice.objects.filter(client=client).aggregate(s=Sum('amount_paid'))['s'] or 0
        balance = out - paid
        if balance <= 0:
            continue
        
        inv_nums = ', '.join(Invoice.objects.filter(client=client).exclude(
            status__in=['paid','written_off']).values_list('invoice_number', flat=True)[:4])
        
        # Prepare message
        msg = (f"Dear {client.get_display_name()},\n\n"
               f"Friendly reminder from {sender['name']}.\n\n"
               f"Outstanding balance: UGX {balance:,.0f}\n"
               f"Reference: {inv_nums}\n\n"
               f"Please make payment to avoid service interruption.\n"
               f"Pay to: {sender['whatsapp']} (Mobile Money)\n"
               f"Email: {sender['email']}\n\nThank you.")
        
        # Send WhatsApp
        wa = client.get_whatsapp_number()
        if wa:
            send_whatsapp_message(wa, msg, client=client, msg_type='debt_reminder')
            sent_whatsapp += 1
        
        # Send Email
        if client.email:
            subject = f"Payment Reminder - Outstanding Balance UGX {balance:,.0f}"
            send_email_notification(client.email, subject, msg, client=client, msg_type='debt_reminder')
            sent_email += 1
    
    return {'whatsapp': sent_whatsapp, 'email': sent_email}


def send_manager_debt_report():
    """Sat/Mon: send debt report to all configured managers."""
    from billing.models import Invoice
    from clients.models import Client
    from django.db.models import Sum
    contacts = get_notify_contacts()
    if not contacts:
        return 0

    clients_q = Client.objects.filter(
        invoices__status__in=['overdue', 'partially_paid']).distinct()
    lines = []
    grand_total = 0
    for i, client in enumerate(clients_q, 1):
        out = Invoice.objects.filter(client=client).exclude(status__in=['paid','written_off']).aggregate(s=Sum('grand_total'))['s'] or 0
        paid = Invoice.objects.filter(client=client).aggregate(s=Sum('amount_paid'))['s'] or 0
        balance = out - paid
        if balance <= 0:
            continue
        oldest = Invoice.objects.filter(client=client).exclude(status__in=['paid','written_off']).order_by('due_date').first()
        days = (timezone.now().date() - oldest.due_date).days if oldest and oldest.due_date < timezone.now().date() else 0
        grand_total += balance
        lines.append(f"{i}. {client.get_display_name()} — UGX {balance:,.0f} ({days}d overdue)")

    if not lines:
        lines = ['✅ No outstanding debts today.']

    msg = (f"TAXMAN256 DEBT REPORT\n{timezone.now().strftime('%A %d %B %Y')}\n\n"
           + '\n'.join(lines) +
           f"\n\nTotal: UGX {grand_total:,.0f}\nClients: {len([l for l in lines if l.startswith('1') or '.' in l[:3]])}")

    for contact in contacts:
        send_whatsapp_message(contact['number'], msg, msg_type='internal_alert')
    return len(contacts)


def send_incomplete_task_reminders():
    """Send reminders to staff about incomplete job cards."""
    from services.models import JobCard
    from core.models import User
    from django.db.models import Count
    today = timezone.now().date()

    # Group open jobs by assigned user
    for user in User.objects.filter(is_active=True, receive_task_reminders=True):
        if not user.phone_whatsapp:
            continue
        open_jobs = JobCard.objects.filter(
            assigned_to=user,
            status__in=['open', 'in_progress'],
        )
        if not open_jobs.exists():
            continue
        overdue_jobs = open_jobs.filter(due_date__lt=today)
        job_lines = []
        for job in open_jobs[:8]:
            due = f" (DUE {job.due_date})" if job.due_date else ''
            urgent = ' ⚠️ OVERDUE' if job.due_date and job.due_date < today else ''
            job_lines.append(f"• {job.job_number} — {job.client.get_display_name()}{due}{urgent}")

        msg = (f"Hi {user.get_full_name() or user.username},\n\n"
               f"TAXMAN256 — Pending Tasks Reminder\n\n"
               f"You have {open_jobs.count()} incomplete job card(s):\n"
               + '\n'.join(job_lines) +
               (f"\n\n⚠️ {overdue_jobs.count()} job(s) are OVERDUE — please action today." if overdue_jobs.exists() else '') +
               f"\n\nLog in to update: http://127.0.0.1:8000/jobs/\nTaxman256")
        send_whatsapp_message(user.phone_whatsapp, msg, msg_type='internal_alert', triggered_by=None)
