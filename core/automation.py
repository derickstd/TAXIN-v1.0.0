"""
Automation utilities and status tracking
"""
from django.utils import timezone
from django.core.cache import cache
from decimal import Decimal


def get_automation_status():
    """Get status of recent automation tasks"""
    from billing.models import Invoice
    from clients.models import Client
    from services.models import JobCard
    from compliance.models import ComplianceDeadline
    
    today = timezone.now().date()
    
    status = {
        'last_run': cache.get('automation_last_run', 'Never'),
        'overdue_invoices_updated': Invoice.objects.filter(
            status='overdue',
            updated_at__date=today
        ).count(),
        'suspended_clients': Client.objects.filter(status='suspended').count(),
        'dormant_clients': Client.objects.filter(status='dormant').count(),
        'upcoming_deadlines': ComplianceDeadline.objects.filter(
            due_date__gte=today,
            due_date__lte=today + timezone.timedelta(days=7),
            status='upcoming'
        ).count(),
        'auto_generated_jobs_today': JobCard.objects.filter(
            is_periodic=True,
            created_at__date=today
        ).count(),
        'pending_payments': Invoice.objects.filter(
            status__in=['sent', 'partially_paid', 'overdue']
        ).count(),
    }
    
    return status


def mark_automation_run():
    """Mark that automation has run"""
    cache.set('automation_last_run', timezone.now().strftime('%Y-%m-%d %H:%M'), 86400)


def get_automation_recommendations():
    """Get smart recommendations based on system state"""
    from billing.models import Invoice
    from clients.models import Client
    from services.models import JobCard
    
    recommendations = []
    
    # Check for invoices pending generation
    jobs_without_invoice = JobCard.objects.filter(
        status__in=['in_progress', 'pending_payment']
    ).exclude(invoice__isnull=False).count()
    
    if jobs_without_invoice > 0:
        recommendations.append({
            'type': 'warning',
            'title': f'{jobs_without_invoice} job cards without invoices',
            'action': 'Review and generate invoices',
            'url': '/jobs/?status=in_progress'
        })
    
    # Check for overdue invoices
    overdue_high_value = Invoice.objects.filter(
        status='overdue',
        grand_total__gte=500000
    ).count()
    
    if overdue_high_value > 0:
        recommendations.append({
            'type': 'danger',
            'title': f'{overdue_high_value} high-value invoices overdue',
            'action': 'Follow up immediately',
            'url': '/billing/?status=overdue'
        })
    
    # Check for suspended clients
    suspended = Client.objects.filter(status='suspended').count()
    if suspended > 0:
        recommendations.append({
            'type': 'info',
            'title': f'{suspended} clients suspended',
            'action': 'Review suspension status',
            'url': '/clients/?status=suspended'
        })
    
    # Check for completed jobs without payment
    completed_unpaid = JobCard.objects.filter(
        status='completed',
        invoice__status__in=['sent', 'partially_paid', 'overdue']
    ).count()
    
    if completed_unpaid > 0:
        recommendations.append({
            'type': 'warning',
            'title': f'{completed_unpaid} completed jobs awaiting payment',
            'action': 'Send payment reminders',
            'url': '/billing/?status=sent'
        })
    
    return recommendations


def auto_generate_missing_invoices():
    """Generate invoices for job cards that don't have one"""
    from services.models import JobCard
    from billing.models import Invoice
    from core.models import User
    
    admin = User.objects.filter(role='admin', is_active=True).first()
    jobs = JobCard.objects.filter(
        status__in=['in_progress', 'pending_payment']
    ).exclude(invoice__isnull=False)
    
    created = 0
    for job in jobs:
        if job.total_fee <= 0:
            continue
        
        subtotal = sum(li.negotiated_price for li in job.line_items.all())
        vat_total = sum(li.vat_amount for li in job.line_items.all())
        
        Invoice.objects.create(
            client=job.client,
            job_card=job,
            due_date=job.due_date or (timezone.now().date() + timezone.timedelta(days=14)),
            subtotal=subtotal,
            vat_total=vat_total,
            grand_total=subtotal + vat_total,
            status='draft',
            created_by=admin
        )
        created += 1
    
    return created
