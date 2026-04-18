from django.utils import timezone
import logging
logger = logging.getLogger(__name__)

def global_context(request):
    ctx = {'firm_name': 'Taxman256', 'firm_phone': '+256785230670', 'firm_email': 'taxissues.go@gmail.com'}
    if not request.user.is_authenticated:
        return ctx
    try:
        from billing.models import Invoice
        from services.models import JobCard
        from compliance.models import ComplianceDeadline
        today = timezone.now().date()
        ctx['overdue_invoices_count'] = Invoice.objects.filter(status='overdue').count()
        ctx['pending_jobs_count']     = JobCard.objects.filter(status__in=['open','in_progress']).count()
        seven_days = today + timezone.timedelta(days=7)
        ctx['upcoming_deadlines_count'] = ComplianceDeadline.objects.filter(
            status='upcoming', due_date__lte=seven_days).count()
        ctx['pending_task_count'] = JobCard.objects.filter(
            assigned_to=request.user, status__in=['open','in_progress']).count()
    except Exception:
        logger.exception('global_context failed')
    return ctx
