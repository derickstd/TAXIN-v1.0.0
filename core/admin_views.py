"""Admin dashboard views for managing users, tenants, and system functions."""
import logging
import csv
import json
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django import forms
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Q, Count
from .models import User, Company, Tenant, AuditLog, Branch
from clients.models import Client

logger = logging.getLogger(__name__)

class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['name', 'slug', 'address', 'phone', 'is_active']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
        }

# Role hierarchy: superuser > admin > moderator > auditor > support
ROLE_PERMISSIONS = {
    'superuser': ['*'],  # Full access
    'admin': ['users', 'companies', 'tenants', 'audit', 'settings', 'support'],
    'moderator': ['tenants', 'audit', 'support'],
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
    
    # Check for admin staff role
    if request.user.is_staff:
        role = getattr(request.user, 'role', 'support')
        if role in ROLE_PERMISSIONS:
            permissions = ROLE_PERMISSIONS.get(role, [])
            
            # Check if user has required permission
            if required_permission == '*' or '*' in permissions:
                return True, role, permissions
            if required_permission in permissions:
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
    tenants = Tenant.objects.all()
    users = User.objects.all()
    
    # Advanced statistics
    stats = {
        'total_companies': companies.count(),
        'active_companies': companies.filter(active=True).count(),
        'inactive_companies': companies.filter(active=False).count(),
        'total_users': users.count(),
        'active_users': users.filter(is_active=True).count(),
        'inactive_users': users.filter(is_active=False).count(),
        'admin_users': users.filter(is_staff=True).count(),
        'total_tenants': tenants.count(),
        'ready_tenants': tenants.filter(status='ready').count(),
        'pending_tenants': tenants.filter(status='pending').count(),
        'running_tenants': tenants.filter(status='running').count(),
        'suspended_tenants': tenants.filter(status='suspended').count(),
        'failed_tenants': tenants.filter(status='failed').count(),
        'recent_signups': users.filter(date_joined__gte=timezone.now() - timedelta(days=7)).count(),
        'total_logs': AuditLog.objects.count(),
    }
    
    # Recent activity
    recent_activity = AuditLog.objects.select_related('changed_by').order_by('-changed_at')[:10]
    
    context = {
        'stats': stats,
        'admin_role': role,
        'permissions': perms,
        'recent_activity': recent_activity,
    }
    
    return render(request, 'core/admin_dashboard.html', context)


@login_required
def admin_send_password_reset(request, user_id):
    """Generate password reset link and email to user."""
    if not _require_admin_role(request, 'users'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    user = get_object_or_404(User, pk=user_id)
    
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
    
    users = User.objects.select_related('company').all().order_by('-date_joined')
    
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

    company = get_object_or_404(Company, pk=company_id)
    branches = company.branches.order_by('name')
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            branch = form.save(commit=False)
            branch.company = company
            branch.save()
            messages.success(request, 'Branch created successfully.')
            return redirect('core:admin_company_branches', company_id=company.pk)
    else:
        form = BranchForm()

    return render(request, 'core/admin_company_branches.html', {
        'company': company,
        'branches': branches,
        'form': form,
    })


@login_required
def admin_tenants(request):
    """List and manage tenants."""
    if not _require_admin_role(request, 'tenants'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    # Search and filter
    search_q = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
    tenants = Tenant.objects.select_related('company', 'created_by').all().order_by('-created_at')
    
    if search_q:
        tenants = tenants.filter(Q(company__name__icontains=search_q) | Q(company__slug__icontains=search_q))
    
    if status_filter and status_filter != 'all':
        tenants = tenants.filter(status=status_filter)
    
    context = {
        'tenants': tenants,
        'search_q': search_q,
        'status_filter': status_filter,
    }
    
    return render(request, 'core/admin_tenants.html', context)


@login_required
def admin_tenant_approve(request, tenant_id):
    """Approve a pending tenant."""
    if not _require_admin_role(request, 'tenants'):
        return JsonResponse({'error': 'Admin access required'}, status=403)
    
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    
    if tenant.status != 'pending':
        return JsonResponse({'error': 'Only pending tenants can be approved'}, status=400)
    
    try:
        tenant.status = 'ready'
        tenant.save()
        
        AuditLog.objects.create(
            model_name='tenant',
            object_id=str(tenant.pk),
            action='UPDATE',
            changed_fields={'status': 'pending → ready'},
            changed_by=request.user,
            notes=f'Tenant {tenant.company.slug} approved by {request.user.username}'
        )
        
        messages.success(request, f'Tenant {tenant.company.slug} approved')
    except Exception as e:
        logger.exception('Failed to approve tenant %s: %s', tenant.pk, e)
        messages.error(request, f'Failed to approve tenant: {str(e)}')
    
    return redirect('core:admin_tenants')


@login_required
def admin_tenant_suspend(request, tenant_id):
    """Suspend an active tenant."""
    if not _require_admin_role(request, 'tenants'):
        return JsonResponse({'error': 'Admin access required'}, status=403)
    
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    
    if tenant.status == 'suspended':
        return JsonResponse({'error': 'Tenant is already suspended'}, status=400)
    
    try:
        old_status = tenant.status
        tenant.status = 'suspended'
        tenant.save()
        
        AuditLog.objects.create(
            model_name='tenant',
            object_id=str(tenant.pk),
            action='UPDATE',
            changed_fields={'status': f'{old_status} → suspended'},
            changed_by=request.user,
            notes=f'Tenant {tenant.company.slug} suspended by {request.user.username}'
        )
        
        messages.success(request, f'Tenant {tenant.company.slug} suspended')
    except Exception as e:
        logger.exception('Failed to suspend tenant %s: %s', tenant.pk, e)
        messages.error(request, f'Failed to suspend tenant: {str(e)}')
    
    return redirect('core:admin_tenants')


@login_required
def admin_tenant_reactivate(request, tenant_id):
    """Reactivate a suspended tenant."""
    if not _require_admin_role(request, 'tenants'):
        return JsonResponse({'error': 'Admin access required'}, status=403)
    
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    
    if tenant.status != 'suspended':
        return JsonResponse({'error': 'Only suspended tenants can be reactivated'}, status=400)
    
    try:
        tenant.status = 'ready'
        tenant.save()
        
        AuditLog.objects.create(
            model_name='tenant',
            object_id=str(tenant.pk),
            action='UPDATE',
            changed_fields={'status': 'suspended → ready'},
            changed_by=request.user,
            notes=f'Tenant {tenant.company.slug} reactivated by {request.user.username}'
        )
        
        messages.success(request, f'Tenant {tenant.company.slug} reactivated')
    except Exception as e:
        logger.exception('Failed to reactivate tenant %s: %s', tenant.pk, e)
        messages.error(request, f'Failed to reactivate tenant: {str(e)}')
    
    return redirect('core:admin_tenants')


@login_required
def admin_audit_logs(request):
    """View audit logs."""
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
    
    logs = AuditLog.objects.select_related('changed_by').filter(changed_at__gte=start_date).order_by('-changed_at')
    
    if search_q:
        logs = logs.filter(Q(model_name__icontains=search_q) | Q(object_id__icontains=search_q) | Q(notes__icontains=search_q))
    
    if model_filter:
        logs = logs.filter(model_name=model_filter)
    
    if action_filter:
        logs = logs.filter(action=action_filter)
    
    context = {
        'logs': logs[:1000],  # Limit to 1000 records
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
    
    user = get_object_or_404(User, pk=user_id)
    
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
    
    user = get_object_or_404(User, pk=user_id)
    
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

    client = get_object_or_404(Client, pk=client_id)

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

    client = get_object_or_404(Client, pk=client_id)

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

    user = get_object_or_404(User, pk=user_id)

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
    
    company = get_object_or_404(Company, pk=company_id)
    
    if not company.active:
        messages.warning(request, f'Company {company.name} is already suspended.')
        return redirect('admin_companies')
    
    try:
        company.active = False
        company.save()
        
        # Also suspend associated tenant
        tenant = Tenant.objects.filter(company=company).first()
        if tenant:
            tenant.status = 'suspended'
            tenant.save()
        
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
    
    company = get_object_or_404(Company, pk=company_id)
    
    if company.active:
        messages.warning(request, f'Company {company.name} is already active.')
        return redirect('admin_companies')
    
    try:
        company.active = True
        company.save()
        
        # Also reactivate associated tenant
        tenant = Tenant.objects.filter(company=company).first()
        if tenant and tenant.status == 'suspended':
            tenant.status = 'ready'
            tenant.save()
        
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
    if not _require_admin_role(request, 'audit'):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    # Advanced statistics
    companies = Company.objects.all()
    users = User.objects.all()
    tenants = Tenant.objects.all()
    
    # Time-based statistics
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    
    analytics = {
        # Company stats
        'total_companies': companies.count(),
        'active_companies': companies.filter(active=True).count(),
        'companies_last_7days': companies.filter(created_at__gte=week_ago).count(),
        'companies_last_30days': companies.filter(created_at__gte=month_ago).count(),
        
        # User stats
        'total_users': users.count(),
        'active_users': users.filter(is_active=True).count(),
        'admin_users': users.filter(is_staff=True).count(),
        'users_last_7days': users.filter(date_joined__gte=week_ago).count(),
        'users_last_30days': users.filter(date_joined__gte=month_ago).count(),
        
        # Tenant stats
        'total_tenants': tenants.count(),
        'ready_tenants': tenants.filter(status='ready').count(),
        'pending_tenants': tenants.filter(status='pending').count(),
        'suspended_tenants': tenants.filter(status='suspended').count(),
        'failed_tenants': tenants.filter(status='failed').count(),
        
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
    logs = AuditLog.objects.filter(changed_at__gte=start_date).order_by('-changed_at')
    
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
        'total_users': User.objects.count(),
        'total_tenants': Tenant.objects.count(),
        'audit_logs_count': AuditLog.objects.count(),
        'pending_tenants': Tenant.objects.filter(status='pending').count(),
        'failed_tenants': Tenant.objects.filter(status='failed').count(),
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
                user = User.objects.get(pk=user_id)
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
    
    users = User.objects.filter(is_active=True).order_by('username')
    return render(request, 'core/admin_bulk_password_reset.html', {'users': users})

