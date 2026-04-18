import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


def update_client_statuses():
    from clients.models import Client
    from billing.models import Invoice
    from services.models import JobCard
    today = timezone.now().date()
    sixty_ago = today - timezone.timedelta(days=60)
    for client in Client.objects.filter(status='active'):
        last = JobCard.objects.filter(client=client).order_by('-created_at').first()
        if not last or last.created_at.date() < sixty_ago:
            Client.objects.filter(pk=client.pk).update(status='dormant')
    ids = Invoice.objects.filter(status__in=['overdue','partially_paid','sent'],
        due_date__lt=sixty_ago).values_list('client_id', flat=True).distinct()
    Client.objects.filter(pk__in=ids).exclude(status__in=['blacklisted','suspended']).update(status='suspended')
    Invoice.objects.filter(status__in=['sent','partially_paid'], due_date__lt=today).update(status='overdue')
    logger.info("Client statuses updated")


def send_friday_client_reminders():
    from notifications.services import send_debt_reminders
    n = send_debt_reminders()
    logger.info(f"Friday reminders sent: {n} clients")


def send_manager_debt_report():
    from notifications.services import send_manager_debt_report as _send
    n = _send()
    logger.info(f"Manager report sent to {n} contacts")


def send_task_reminders():
    from notifications.services import send_incomplete_task_reminders
    send_incomplete_task_reminders()
    logger.info("Task reminders sent")


def generate_monthly_jobcards():
    from services.models import ClientServiceSubscription, JobCard, JobCardLineItem
    from billing.models import Invoice
    from core.models import User
    import calendar
    today = timezone.now().date()
    month, year = today.month, today.year
    label = f"{calendar.month_name[month]} {year}"
    admin = User.objects.filter(role='admin').first()
    created = 0
    for sub in ClientServiceSubscription.objects.filter(is_active=True, service_type__is_recurring=True).select_related('client','service_type','client__assigned_officer'):
        exists = JobCard.objects.filter(client=sub.client, period_month=month, period_year=year,
            line_items__service_type=sub.service_type).exists()
        if exists:
            continue
        job, new = JobCard.objects.get_or_create(
            client=sub.client, period_month=month, period_year=year, is_periodic=True,
            defaults={'assigned_to': sub.client.assigned_officer, 'status': 'open', 'created_by': admin})
        import datetime
        due_m = month+1 if month<12 else 1
        due_y = year if month<12 else year+1
        if sub.service_type.deadline_type == 'monthly_15':
            job.due_date = datetime.date(due_y, due_m, 15)
        elif sub.service_type.deadline_type == 'annual_dec31':
            job.due_date = datetime.date(year, 12, 31)
        job.save(update_fields=['due_date'])
        JobCardLineItem.objects.create(job_card=job, service_type=sub.service_type,
            default_price=sub.service_type.default_price, negotiated_price=sub.negotiated_price,
            status='not_handled', period_label=label)
        job.update_total()
        if new:
            try:
                Invoice.objects.create(client=sub.client, job_card=job,
                    due_date=job.due_date or (today + timezone.timedelta(days=14)),
                    subtotal=sub.negotiated_price, vat_total=0, grand_total=sub.negotiated_price,
                    status='draft', created_by=admin)
            except Exception:
                pass
        created += 1
    logger.info(f"Monthly job cards: {created} created for {label}")


def generate_compliance_deadlines():
    from compliance.models import ComplianceObligation, ComplianceDeadline
    import calendar, datetime
    today = timezone.now().date()
    month, year = today.month, today.year
    label = f"{calendar.month_name[month]} {year}"
    created = 0
    for obl in ComplianceObligation.objects.filter(is_active=True).select_related('service_type'):
        dt = obl.service_type.deadline_type
        if dt == 'monthly_15':
            due_m = month+1 if month<12 else 1; due_y = year if month<12 else year+1
            due = datetime.date(due_y, due_m, 15); period = label
        elif dt == 'annual_dec31':
            due = datetime.date(year, 12, 31); period = f"FY{year}"
        elif dt == 'annual_jun30':
            due = datetime.date(year, 6, 30); period = f"FY{year}"
        else:
            continue
        _, new = ComplianceDeadline.objects.get_or_create(
            obligation=obl, period_label=period, defaults={'due_date': due, 'status': 'upcoming'})
        if new: created += 1
    logger.info(f"Compliance deadlines: {created} new for {label}")
