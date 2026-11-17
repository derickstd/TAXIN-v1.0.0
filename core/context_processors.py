from django.utils import timezone
import json
import logging
from .branch_access import scope_queryset
from .utils import get_module_visibility_map
logger = logging.getLogger(__name__)

def global_context(request):
    ctx = {'firm_name': 'Taxin', 'firm_phone': '+256785230670', 'firm_email': 'taxissues.go@gmail.com'}
    ctx['active_branch'] = getattr(request, 'active_branch', None)
    ctx['workspace_branches'] = getattr(request, 'workspace_branches', ())
    ctx['can_switch_branch'] = getattr(request, 'can_switch_branch', False)
    ctx['external_reporting_workspace'] = bool(
        ctx['active_branch'] and ctx['active_branch'].external_reporting,
    )
    company = getattr(request.user, 'company', None)
    module_visibility = get_module_visibility_map(company=company)
    ctx['module_visibility'] = {key: module.enabled for key, module in module_visibility.items()}
    ctx['module_labels'] = {key: module.label for key, module in module_visibility.items()}
    ctx['module_orders'] = {key: module.order for key, module in module_visibility.items()}
    ctx['module_orders_json'] = json.dumps(ctx['module_orders'])
    if not request.user.is_authenticated:
        return ctx
    try:
        from billing.models import Invoice
        from services.models import JobCard
        from compliance.models import ComplianceDeadline
        today = timezone.now().date()
        ctx['overdue_invoices_count'] = scope_queryset(
            request.user, Invoice.objects.filter(status='overdue'),
        ).count()
        ctx['pending_jobs_count'] = scope_queryset(
            request.user, JobCard.objects.filter(status__in=['open', 'in_progress']),
        ).count()
        seven_days = today + timezone.timedelta(days=7)
        ctx['upcoming_deadlines_count'] = scope_queryset(
            request.user,
            ComplianceDeadline.objects.filter(
                status='upcoming', due_date__lte=seven_days,
            ),
            branch_path='obligation__client__branch',
        ).count()
        ctx['pending_task_count'] = scope_queryset(
            request.user,
            JobCard.objects.filter(
                assigned_to=request.user, status__in=['open', 'in_progress'],
            ),
        ).count()
    except Exception:
        logger.exception('global_context failed')
    return ctx

