"""Admin dashboard views for the company, branches, users, and system functions."""
import logging
import csv
import json
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Q, Count
from .models import User, Company, AuditLog, Branch, SystemModuleVisibility
from .utils import get_module_visibility_map, SYSTEM_MODULE_DEFINITIONS
from clients.models import Client
from .branch_access import scope_queryset
from .branch_setup import ensure_business_branches

logger = logging.getLogger(__name__)


def _managed_users(request):
    users = scope_queryset(request.user, User.objects.select_related('company', 'branch'))
    if request.user.role == 'manager' and not request.user.is_superuser:
        users = users.exclude(role__in=('admin', 'ceo'))
    return users


# Role hierarchy: superuser > admin > moderator > auditor > support
ROLE_PERMISSIONS = {
    'superuser': ['*'],  # Full access
    'admin': ['users', 'companies', 'audit', 'settings', 'support'],
    'ceo': ['users', 'companies', 'audit', 'settings', 'support'],
    'manager': ['users', 'audit'],
    'moderator': ['audit', 'support'],
    'auditor': ['audit'],
    'support': ['users.reset_password', 'audit.view'],
}


def _check_admin_role(request, required_permission='admin'):
    """
    Check if user has required admin role and permissions.
    Returns (has_access, user_role, permissions)
    """
    if not request.user.is_authenticated:
        return False, None, []
    
    # Superuser has full access
    if request.user.is_superuser:
        return True, 'superuser', ROLE_PERMISSIONS['superuser']
    
    role = getattr(request.user, 'role', 'support')
    if role not in ROLE_PERMISSIONS:
        return False, None, []

    permissions = ROLE_PERMISSIONS[role]
    if required_permission == '*':
        return role in ('admin', 'ceo'), role, permissions
    if '*' in permissions or required_permission in permissions:
        return True, role, permissions
    return False, None, []


def _require_admin_role(request, permission='admin'):
    """Decorator-like check for admin role."""
    has_access, role, perms = _check_admin_role(request, permission)
    if not has_access:
        messages.error(request, f'Admin access required ({permission}).')
        return False
    return True


@login_required
def admin_dashboard(request):
    """Main admin dashboard showing system statistics and options."""
    if not _require_admin_role(request, '*'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    has_access, role, perms = _check_admin_role(request, '*')
    
    companies = Company.objects.all()
    branches = Branch.objects.all()
    users = User.objects.all()
    audit_logs = AuditLog.objects.all()
    if not request.user.is_superuser:
        companies = companies.filter(pk=request.user.company_id)
        branches = branches.filter(company_id=request.user.company_id)
        users = users.filter(company_id=request.user.company_id)
        audit_logs = audit_logs.filter(changed_by__company_id=request.user.company_id)
    
    # Advanced statistics
    stats = {
        'total_companies': companies.count(),
        'active_companies': companies.filter(active=True).count(),
        'inactive_companies': companies.filter(active=False).count(),
        'total_branches': branches.count(),
        'active_branches': branches.filter(is_active=True).count(),
        'total_users': users.count(),
        'active_users': users.filter(is_active=True).count(),
        'inactive_users': users.filter(is_active=False).count(),
        'admin_users': users.filter(is_staff=True).count(),
        'recent_signups': users.filter(date_joined__gte=timezone.now() - timedelta(days=7)).count(),
        'total_logs': audit_logs.count(),
    }
    
    # Recent activity
    recent_activity = audit_logs.select_related('changed_by').order_by('-changed_at')[:10]
    
    context = {
        'stats': stats,
        'admin_role': role,
        'permissions': perms,
        'recent_activity': recent_activity,
    }
    
    return render(request, 'core/admin_dashboard.html', context)


@login_required
def admin_control_center(request):
    """Central administration page for visibility toggles and management shortcuts."""
    if not _require_admin_role(request, '*'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')

    company = getattr(request.user, 'company', None)
    can_manage_roles = request.user.is_superuser or request.user.role in ('admin', 'ceo')
    company_users = User.objects.filter(company=company).order_by('first_name', 'last_name', 'username') if company else User.objects.none()

    if request.method == 'POST':
        for key, label, description in SYSTEM_MODULE_DEFINITIONS:
            field_name = f'module_{key}'
            module, created = SystemModuleVisibility.objects.get_or_create(
                key=key,
                company=company,
                defaults={'label': label, 'description': description, 'enabled': True},
            )
            raw_value = request.POST.get(field_name)
            module.enabled = raw_value != 'off'
            module.label = (request.POST.get(f'module_label_{key}') or label).strip()[:100]
            try:
                module.order = max(0, int(request.POST.get(f'module_order_{key}', module.order)))
            except (TypeError, ValueError):
                pass
            module.save(update_fields=['enabled', 'label', 'order'])

        if can_manage_roles:
            role_user_id = request.POST.get('role_user')
            role_user = company_users.filter(pk=role_user_id).first() if role_user_id else None
            role = request.POST.get('role')
            allowed_roles = dict(User.ROLE_CHOICES)
            if role_user and role in allowed_roles and role not in ('superuser',):
                role_user.role = role
                role_user.is_staff = role in ('admin', 'ceo', 'manager')
                role_user.save(update_fields=['role', 'is_staff'])

        messages.success(request, 'System controls updated successfully.')
        return redirect('core:admin_control_center')

    module_rows = []
    module_map = get_module_visibility_map(company=company)
    for key, label, description in SYSTEM_MODULE_DEFINITIONS:
        module = module_map.get(key)
        if module:
            module_rows.append({
                'key': module.key,
                'label': module.label,
                'description': module.description or description,
                'enabled': module.enabled,
                'order': module.order,
            })

    quick_links = [
        {'label': 'Client management', 'url': 'clients:list', 'icon': 'fas fa-users', 'description': 'Create, review, and manage company clients.'},
        {'label': 'Engagements', 'url': 'services:list', 'icon': 'fas fa-briefcase', 'description': 'Open job cards and manage company work.'},
        {'label': 'Invoices and receipts', 'url': 'billing:list', 'icon': 'fas fa-receipt', 'description': 'Track company invoices, payments, and receipts.'},
        {'label': 'Expenses', 'url': 'expenses:list', 'icon': 'fas fa-wallet', 'description': 'Review and manage company expenses.'},
        {'label': 'Compliance', 'url': 'compliance:list', 'icon': 'fas fa-balance-scale', 'description': 'Manage company deadlines, reminders, and filings.'},
        {'label': 'Documents and reports', 'url': 'documents:monthly_report', 'icon': 'fas fa-file-alt', 'description': 'Open company reports and documents.'},
    ]

    return render(request, 'core/admin_control_center.html', {
        'modules': module_rows,
        'quick_links': quick_links,
        'company_name': company.name if company else 'the company',
        'company_users': company_users,
        'role_choices': User.ROLE_CHOICES,
        'can_manage_roles': can_manage_roles,
    })


@login_required
def admin_send_password_reset(request, user_id):
    """Generate password reset link and email to user."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    user = get_object_or_404(_managed_users(request), pk=user_id)
    
    if request.method == 'POST':
        try:
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            reset_url = f"{request.build_absolute_uri('/password-reset-confirm/')}{uid}/{token}/"
            
            subject = 'Password Reset for Taxin'
            message = f"""
Hello {user.first_name or user.username},

An administrator has requested a password reset for your Taxin account.

Click the link below to set a new password:
{reset_url}

This link will expire in 1 day.

If you did not request this, please contact your administrator.

Thank you,
Taxin
            """
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            
            AuditLog.objects.create(
                model_name='user',
                object_id=str(user.pk),
                action='UPDATE',
                changed_fields={'reset_password_sent': True},
                changed_by=request.user,
                notes=f'Password reset email sent to {user.email} by admin'
            )
            
            messages.success(request, f'Password reset link sent to {user.email}')
        except Exception as e:
            logger.exception('Failed to send password reset email for user %s: %s', user.username, e)
            messages.error(request, f'Failed to send email: {str(e)}')
        
        return redirect('core:admin_users')
    
    return render(request, 'core/admin_send_password_reset.html', {'user': user})


@login_required
def admin_users(request):
    """List and manage users."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    # Search and filter
    search_q = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
    users = _managed_users(request).order_by('-date_joined')
    
    if search_q:
        users = users.filter(Q(username__icontains=search_q) | Q(email__icontains=search_q) | Q(first_name__icontains=search_q))
    
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    elif status_filter == 'admin':
        users = users.filter(is_staff=True)
    
    context = {
        'users': users,
        'search_q': search_q,
        'status_filter': status_filter,
    }
    
    return render(request, 'core/admin_users.html', context)


@login_required
def admin_companies(request):
    """List and manage companies."""
    if not _require_admin_role(request, 'companies'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    # Search and filter
    search_q = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
    companies = Company.objects.select_related('owner').all().order_by('-created_at')
    if not request.user.is_superuser:
        companies = companies.filter(pk=request.user.company_id)
    
    if search_q:
        companies = companies.filter(Q(name__icontains=search_q) | Q(slug__icontains=search_q) | Q(email__icontains=search_q))
    
    if status_filter == 'active':
        companies = companies.filter(active=True)
    elif status_filter == 'inactive':
        companies = companies.filter(active=False)
    
    context = {
        'companies': companies,
        'search_q': search_q,
        'status_filter': status_filter,
    }
    
    return render(request, 'core/admin_companies.html', context)


@login_required
def admin_company_branches(request, company_id):
    if not _require_admin_role(request, 'companies'):
        return redirect('dashboard:index')

    if not request.user.is_superuser and request.user.role not in ('admin', 'ceo'):
        messages.error(request, 'Only company leadership can manage branches.')
        return redirect('dashboard:index')
    companies = Company.objects.all() if request.user.is_superuser else Company.objects.filter(pk=request.user.company_id)
    company = get_object_or_404(companies, pk=company_id)
    branches = company.branches.order_by('name')
    if request.method == 'POST':
        if request.POST.get('action') != 'setup_business_branches':
            messages.error(request, 'Only TAXMAN, PRIME FOCUS, and ABA UGANDA are supported branches.')
            return redirect('core:admin_company_branches', company_id=company.pk)

        ensure_business_branches(company)
        messages.success(request, 'TAXMAN, PRIME FOCUS, and ABA UGANDA are ready.')
        return redirect('core:admin_company_branches', company_id=company.pk)

    return render(request, 'core/admin_company_branches.html', {
        'company': company,
        'branches': branches,
    })


@login_required
def admin_audit_logs(request):
    """View system, transaction, and job activity logs in one feed."""
    if not _require_admin_role(request, 'audit'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    # Search and filter
    search_q = request.GET.get('search', '')
    model_filter = request.GET.get('model', '')
    action_filter = request.GET.get('action', '')
    days_filter = request.GET.get('days', '30')
    
    # Calculate date range
    try:
        days = int(days_filter) if days_filter else 30
    except:
        days = 30
    
    start_date = timezone.now() - timedelta(days=days)
    
    from services.models import StaffActivityLog
    from .models import TransactionEditLog

    logs = []
    audit_logs = scope_queryset(
        request.user,
        AuditLog.objects.select_related('changed_by').filter(changed_at__gte=start_date),
        branch_path='changed_by__branch',
    )
    for log in audit_logs:
        logs.append({
            'changed_at': log.changed_at,
            'model_name': log.model_name,
            'object_id': log.object_id,
            'action': log.action,
            'changed_by': log.changed_by,
            'notes': log.notes,
        })

    activity_logs = scope_queryset(
        request.user,
        StaffActivityLog.objects.select_related('staff', 'job_card').filter(
            created_at__gte=start_date,
        ),
        branch_path='job_card__branch',
    )
    for log in activity_logs:
        logs.append({
            'changed_at': log.created_at,
            'model_name': 'job_card_activity',
            'object_id': str(log.job_card_id),
            'action': 'CREATE' if 'created' in log.action.lower() else 'UPDATE',
            'changed_by': log.staff,
            'notes': log.action or log.description,
        })

    edit_logs = scope_queryset(
        request.user,
        TransactionEditLog.objects.select_related('edited_by').filter(edited_at__gte=start_date),
        branch_path='edited_by__branch',
    )
    for log in edit_logs:
        logs.append({
            'changed_at': log.edited_at,
            'model_name': f'{log.transaction_type}_edit',
            'object_id': str(log.transaction_id),
            'action': 'UPDATE',
            'changed_by': log.edited_by,
            'notes': log.reason or f'{log.get_transaction_type_display()} edited',
        })

    if search_q:
        search_q_lower = search_q.lower()
        logs = [log for log in logs if any(
            search_q_lower in str(log[field]).lower()
            for field in ('model_name', 'object_id', 'notes')
        )]
    if model_filter:
        logs = [log for log in logs if log['model_name'] == model_filter]
    if action_filter:
        logs = [log for log in logs if log['action'] == action_filter]
    logs.sort(key=lambda log: log['changed_at'], reverse=True)
    
    context = {
        'logs': logs[:1000],
        'search_q': search_q,
        'model_filter': model_filter,
        'action_filter': action_filter,
        'days_filter': days_filter,
    }
    
    return render(request, 'core/admin_audit_logs.html', context)


# ==================== ADVANCED ADMIN FUNCTIONS ====================

@login_required
def admin_user_deactivate(request, user_id):
    """Deactivate a user account."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    user = get_object_or_404(_managed_users(request), pk=user_id)
    
    if not user.is_active:
        messages.warning(request, f'User {user.username} is already inactive.')
        return redirect('admin_users')
    
    try:
        user.is_active = False
        user.save()
        
        AuditLog.objects.create(
            model_name='user',
            object_id=str(user.pk),
            action='UPDATE',
            changed_fields={'is_active': 'True → False'},
            changed_by=request.user,
            notes=f'User {user.username} deactivated by {request.user.username}'
        )
        
        messages.success(request, f'User {user.username} has been deactivated.')
    except Exception as e:
        logger.exception('Failed to deactivate user %s: %s', user.pk, e)
        messages.error(request, f'Failed to deactivate user: {str(e)}')
    
    return redirect('core:admin_users')


@login_required
def admin_user_reactivate(request, user_id):
    """Reactivate a deactivated user account."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    user = get_object_or_404(_managed_users(request), pk=user_id)
    
    if user.is_active:
        messages.warning(request, f'User {user.username} is already active.')
        return redirect('admin_users')
    
    try:
        user.is_active = True
        user.save()
        
        AuditLog.objects.create(
            model_name='user',
            object_id=str(user.pk),
            action='UPDATE',
            changed_fields={'is_active': 'False → True'},
            changed_by=request.user,
            notes=f'User {user.username} reactivated by {request.user.username}'
        )
        
        messages.success(request, f'User {user.username} has been reactivated.')
    except Exception as e:
        logger.exception('Failed to reactivate user %s: %s', user.pk, e)
        messages.error(request, f'Failed to reactivate user: {str(e)}')
    
    return redirect('core:admin_users')


@login_required
def admin_client_suspend(request, client_id):
    """Suspend a client account."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')

    client = get_object_or_404(scope_queryset(request.user, Client.objects.all()), pk=client_id)

    if client.status == 'suspended':
        messages.warning(request, f'Client {client.get_display_name()} is already suspended.')
        return redirect('clients:detail', pk=client.pk)

    try:
        old_status = client.status
        client.status = 'suspended'
        client.save(update_fields=['status'])

        AuditLog.objects.create(
            model_name='client',
            object_id=str(client.pk),
            action='UPDATE',
            changed_fields={'status': f'{old_status} → suspended'},
            changed_by=request.user,
            notes=f'Client {client.get_display_name()} suspended by {request.user.username}'
        )

        messages.success(request, f'Client {client.get_display_name()} has been suspended.')
    except Exception as e:
        logger.exception('Failed to suspend client %s: %s', client.pk, e)
        messages.error(request, f'Failed to suspend client: {str(e)}')

    return redirect('clients:detail', pk=client.pk)


@login_required
def admin_client_reactivate(request, client_id):
    """Reactivate a suspended client account."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')

    client = get_object_or_404(scope_queryset(request.user, Client.objects.all()), pk=client_id)

    if client.status != 'suspended':
        messages.warning(request, f'Client {client.get_display_name()} is not suspended.')
        return redirect('clients:detail', pk=client.pk)

    try:
        client.status = 'active'
        client.save(update_fields=['status'])

        AuditLog.objects.create(
            model_name='client',
            object_id=str(client.pk),
            action='UPDATE',
            changed_fields={'status': 'suspended → active'},
            changed_by=request.user,
            notes=f'Client {client.get_display_name()} reactivated by {request.user.username}'
        )

        messages.success(request, f'Client {client.get_display_name()} has been reactivated.')
    except Exception as e:
        logger.exception('Failed to reactivate client %s: %s', client.pk, e)
        messages.error(request, f'Failed to reactivate client: {str(e)}')

    return redirect('clients:detail', pk=client.pk)


@login_required
def admin_user_delete(request, user_id):
    """Delete a user account from the system."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')

    user = get_object_or_404(_managed_users(request), pk=user_id)

    if user == request.user:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('core:admin_users')

    if request.method != 'POST':
        return render(request, 'core/admin_user_confirm_delete.html', {'user': user})

    try:
        username = user.username
        user.delete()

        AuditLog.objects.create(
            model_name='user',
            object_id=str(user_id),
            action='DELETE',
            changed_by=request.user,
            notes=f'User {username} deleted by {request.user.username}'
        )

        messages.success(request, f'User {username} has been deleted.')
    except Exception as e:
        logger.exception('Failed to delete user %s: %s', user_id, e)
        messages.error(request, f'Failed to delete user: {str(e)}')

    return redirect('core:admin_users')


@login_required
def admin_company_suspend(request, company_id):
    """Suspend a company's access."""
    if not _require_admin_role(request, 'companies'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    companies = Company.objects.all() if request.user.is_superuser else Company.objects.filter(
        pk=request.user.company_id,
    )
    company = get_object_or_404(companies, pk=company_id)
    
    if not company.active:
        messages.warning(request, f'Company {company.name} is already suspended.')
        return redirect('admin_companies')
    
    try:
        company.active = False
        company.save()
        
        AuditLog.objects.create(
            model_name='company',
            object_id=str(company.pk),
            action='UPDATE',
            changed_fields={'active': 'True → False'},
            changed_by=request.user,
            notes=f'Company {company.name} suspended by {request.user.username}'
        )
        
        messages.success(request, f'Company {company.name} has been suspended.')
    except Exception as e:
        logger.exception('Failed to suspend company %s: %s', company.pk, e)
        messages.error(request, f'Failed to suspend company: {str(e)}')
    
    return redirect('core:admin_companies')


@login_required
def admin_company_reactivate(request, company_id):
    """Reactivate a suspended company."""
    if not _require_admin_role(request, 'companies'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    companies = Company.objects.all() if request.user.is_superuser else Company.objects.filter(
        pk=request.user.company_id,
    )
    company = get_object_or_404(companies, pk=company_id)
    
    if company.active:
        messages.warning(request, f'Company {company.name} is already active.')
        return redirect('admin_companies')
    
    try:
        company.active = True
        company.save()
        
        AuditLog.objects.create(
            model_name='company',
            object_id=str(company.pk),
            action='UPDATE',
            changed_fields={'active': 'False → True'},
            changed_by=request.user,
            notes=f'Company {company.name} reactivated by {request.user.username}'
        )
        
        messages.success(request, f'Company {company.name} has been reactivated.')
    except Exception as e:
        logger.exception('Failed to reactivate company %s: %s', company.pk, e)
        messages.error(request, f'Failed to reactivate company: {str(e)}')
    
    return redirect('core:admin_companies')


@login_required
def admin_system_analytics(request):
    """View system-wide analytics and statistics."""
    if not request.user.is_superuser:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied()
    if not _require_admin_role(request, 'audit'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    # Advanced statistics
    companies = Company.objects.all()
    users = User.objects.all()
    branches = Branch.objects.all()
    
    # Time-based statistics
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    
    analytics = {
        # Company stats
        'total_companies': companies.count(),
        'active_companies': companies.filter(active=True).count(),
        
        # Branch stats
        'total_branches': branches.count(),
        'active_branches': branches.filter(is_active=True).count(),

        # User stats
        'total_users': users.count(),
        'active_users': users.filter(is_active=True).count(),
        'admin_users': users.filter(is_staff=True).count(),
        'users_last_7days': users.filter(date_joined__gte=week_ago).count(),
        'users_last_30days': users.filter(date_joined__gte=month_ago).count(),
        
        # Audit stats
        'total_audit_logs': AuditLog.objects.count(),
        'audit_logs_7days': AuditLog.objects.filter(changed_at__gte=week_ago).count(),
        'audit_logs_30days': AuditLog.objects.filter(changed_at__gte=month_ago).count(),
        
        # Activity by model
        'logs_by_model': AuditLog.objects.values('model_name').annotate(count=Count('id')).order_by('-count'),
        'logs_by_action': AuditLog.objects.values('action').annotate(count=Count('id')).order_by('-count'),
    }
    
    return render(request, 'core/admin_analytics.html', {'analytics': analytics})


@login_required
def admin_export_audit_logs(request):
    """Export audit logs to CSV."""
    if not _require_admin_role(request, 'audit'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    # Get filter parameters
    days = int(request.GET.get('days', 30)) if request.GET.get('days', '').isdigit() else 30
    model_filter = request.GET.get('model', '')
    
    start_date = timezone.now() - timedelta(days=days)
    logs = scope_queryset(
        request.user, AuditLog.objects.filter(changed_at__gte=start_date),
        branch_path='changed_by__branch',
    ).order_by('-changed_at')
    
    if model_filter:
        logs = logs.filter(model_name=model_filter)
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="audit_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'Model', 'Object ID', 'Action', 'Changed By', 'Changed Fields', 'Notes'])
    
    for log in logs:
        writer.writerow([
            log.changed_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.model_name,
            log.object_id,
            log.action,
            log.changed_by.username if log.changed_by else 'System',
            json.dumps(log.changed_fields) if log.changed_fields else '',
            log.notes,
        ])
    
    AuditLog.objects.create(
        model_name='audit_log',
        object_id='export',
        action='READ',
        changed_fields={'export_format': 'CSV', 'days': days},
        changed_by=request.user,
        notes=f'Audit logs exported by {request.user.username}'
    )
    
    return response


@login_required
def admin_system_health(request):
    """View system health and diagnostics."""
    if not request.user.is_superuser:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied()
    if not _require_admin_role(request, 'audit'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    health_status = {
        'database': 'OK',
        'auth_system': 'OK',
        'audit_logging': 'OK',
        'email_backend': settings.EMAIL_BACKEND,
        'debug_mode': settings.DEBUG,
        'allowed_hosts': len(settings.ALLOWED_HOSTS),
        'total_companies': Company.objects.count(),
        'total_branches': Branch.objects.count(),
        'total_users': User.objects.count(),
        'audit_logs_count': AuditLog.objects.count(),
    }
    
    return render(request, 'core/admin_health.html', {'health': health_status})


@login_required
def admin_bulk_password_reset(request):
    """Send password reset to multiple users."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    if request.method == 'POST':
        user_ids = request.POST.getlist('user_ids')
        
        if not user_ids:
            messages.warning(request, 'No users selected.')
            return redirect('admin_users')
        
        success_count = 0
        error_count = 0
        
        for user_id in user_ids:
            try:
                user = _managed_users(request).get(pk=user_id)
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                reset_url = f"{request.build_absolute_uri('/password-reset-confirm/')}{uid}/{token}/"
                
                send_mail(
                    'Password Reset for Taxin',
                    f'Reset link: {reset_url}',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                
                AuditLog.objects.create(
                    model_name='user',
                    object_id=str(user.pk),
                    action='UPDATE',
                    changed_fields={'reset_password_sent': True},
                    changed_by=request.user,
                    notes=f'Password reset email sent (bulk) to {user.email}'
                )
                
                success_count += 1
            except Exception as e:
                logger.exception('Failed to send password reset to user %s: %s', user_id, e)
                error_count += 1
        
        messages.success(request, f'Password reset sent to {success_count} users.')
        if error_count > 0:
            messages.warning(request, f'{error_count} emails failed to send.')
        
        return redirect('core:admin_users')
    
    users = _managed_users(request).filter(is_active=True).order_by('username')
    return render(request, 'core/admin_bulk_password_reset.html', {'users': users})

