from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import logging
from .models import User, Company, AuditLog, Branch
from django import forms
from django.forms.models import inlineformset_factory
from .export_utils import export_to_excel, export_to_pdf, paginate_list
from .branch_access import scope_queryset


class ConfirmLogoutView(LogoutView):
    http_method_names = ['get', 'post', 'options']

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        return render(request, self.template_name)


class UserForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput, required=False,
                                 help_text='Leave blank to keep existing password')
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'email_notify',
                  'phone_whatsapp', 'branch', 'role', 'ui_theme', 'is_active_staff', 'is_active',
                  'receive_debt_alerts', 'receive_task_reminders', 'date_joined_firm']
        widgets = {'date_joined_firm': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        company_id = getattr(self.instance, 'company_id', None) or getattr(actor, 'company_id', None)
        branches = Branch.objects.filter(is_active=True)
        if company_id:
            branches = branches.filter(company_id=company_id)
        elif actor and not actor.is_superuser and actor.branch_id:
            branches = branches.filter(pk=actor.branch_id)
        elif actor and not actor.is_superuser:
            branches = branches.none()
        active_branch_id = getattr(actor, 'active_branch_id', None)
        if active_branch_id:
            branches = branches.filter(pk=active_branch_id)
        elif actor and not actor.is_superuser and actor.role not in ('admin', 'ceo'):
            branches = branches.filter(pk=actor.branch_id)
        if actor and actor.role == 'manager':
            self.fields['role'].choices = [
                choice for choice in self.fields['role'].choices
                if choice[0] not in ('admin', 'ceo')
            ]
        self.fields['branch'].queryset = branches.order_by('name')
        self.fields['branch'].required = False
        if active_branch_id:
            self.fields['branch'].initial = active_branch_id
        elif actor and actor.branch_id:
            self.fields['branch'].initial = actor.branch_id

    def clean(self):
        cd = super().clean()
        p1, p2 = cd.get('password1'), cd.get('password2')
        if p1 or p2:
            if p1 != p2:
                raise forms.ValidationError('Passwords do not match.')
        role = cd.get('role')
        if self.actor and self.actor.role == 'manager' and role in ('admin', 'ceo'):
            self.add_error('role', 'Branch managers cannot assign company leadership roles.')
        company_id = getattr(self.instance, 'company_id', None) or getattr(self.actor, 'company_id', None)
        if role not in ('admin', 'ceo') and company_id and self.fields['branch'].queryset.exists() and not cd.get('branch'):
            self.add_error('branch', 'Assign this staff member to a branch.')
        return cd


def _save_new_user(form, actor):
    user = form.save(commit=False)
    if not actor.is_superuser and actor.company_id:
        user.company = actor.company
    password = form.cleaned_data.get('password1') or 'taxman2025!'
    user.set_password(password)
    user.is_active = True
    user.is_active_staff = True
    user.save()
    return user, password


class UserSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'email_notify', 'phone_whatsapp',
            'receive_debt_alerts', 'receive_task_reminders', 'ui_theme',
        ]


class CompanySettingsForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name', 'registration_number', 'tin', 'email', 'phone', 'address', 'default_branch']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['default_branch'].queryset = self.instance.branches.all()
        else:
            self.fields['default_branch'].queryset = Branch.objects.none()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')


class BranchSettingsForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = [
            'name', 'slug', 'address', 'phone', 'logo', 'is_active',
            'external_reporting',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'logo': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_logo(self):
        logo = self.files.get(self.add_prefix('logo'))
        if logo and logo.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Branch logos must be 5 MB or smaller.')
        return self.cleaned_data.get('logo')


@never_cache
def offline(request):
    return render(request, 'core/offline.html')


def service_worker(request):
    import os
    from django.http import HttpResponse
    from django.conf import settings
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    with open(sw_path, 'r') as f:
        content = f.read()
    return HttpResponse(content, content_type='application/javascript')


def _require_admin(request):
    return request.user.is_authenticated and (request.user.role in ('admin', 'manager', 'ceo') or request.user.is_superuser)


def _company_users(request):
    if request.user.is_superuser:
        return User.objects.all()
    if request.user.company_id:
        users = User.objects.filter(company=request.user.company)
        if request.user.role == 'manager':
            return users.filter(branch_id=request.user.branch_id)
        return users
    return User.objects.none()


def signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')
    messages.info(request, 'Company registration is disabled. Contact your administrator for access.')
    return redirect('login')


@login_required
def user_list(request):
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    users = _company_users(request).order_by('role', 'first_name')
    can_delete_users = (
        request.user.is_superuser or request.user.role in ('admin', 'ceo')
    )
    return render(request, 'core/user_list.html', {
        'users': users,
        'can_delete_users': can_delete_users,
    })


@login_required
@require_POST
def user_delete(request, pk):
    if not (request.user.is_superuser or request.user.role in ('admin', 'ceo')):
        messages.error(request, 'Only CEOs and admins can delete users.')
        return redirect('core:users')

    if request.user.is_superuser:
        users = User.objects.all()
    elif request.user.company_id:
        users = User.objects.filter(company_id=request.user.company_id)
    else:
        users = User.objects.none()
    user = get_object_or_404(users, pk=pk)

    if user == request.user:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('core:users')

    username = user.username
    user.delete()
    AuditLog.objects.create(
        model_name='user',
        object_id=str(pk),
        action='DELETE',
        changed_by=request.user,
        notes=f'User {username} deleted by {request.user.username}',
    )
    messages.success(request, f'User {username} has been deleted.')
    return redirect('core:users')


@login_required
def user_create(request):
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    if request.method == 'POST':
        form = UserForm(request.POST, actor=request.user)
        if form.is_valid():
            user, password = _save_new_user(form, request.user)
            messages.success(
                request,
                f'User "{user.username}" created. '
                f'Login: username = {user.username}, '
                f'password = {password}. '
                f'Ask them to change it after first login.'
            )
    else:
        form = UserForm(actor=request.user)
    role_guide = [
        ('admin', 'Admin', 'Full access: users, settings, all data, all approvals'),
        ('manager', 'Manager', 'Finance, billing, approvals, reports, no system settings'),
        ('senior_officer', 'Senior Officer', 'All job cards, credentials, reports'),
        ('tax_officer', 'Tax Officer', 'Own job cards, clients, compliance filing'),
        ('receptionist', 'Receptionist', 'Client registration and walk-in intake only'),
    ]
    return render(request, 'core/user_form.html', {
        'form': form, 'title': 'New User', 'is_new': True, 'role_guide': role_guide,
    })


@ensure_csrf_cookie
@csrf_protect
@never_cache
def custom_login(request):
    """Authenticate staff for the single company workspace."""
    from django.contrib.auth import authenticate, login

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.company_id and not user.company.active and not user.is_superuser:
                messages.error(request, 'Company access is suspended. Contact your administrator.')
                return render(request, 'core/login.html')

            login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next', 'dashboard:index')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
            return render(request, 'core/login.html')

    return render(request, 'core/login.html')


@login_required
def user_edit(request, pk):
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    if request.user.is_superuser:
        user = get_object_or_404(User, pk=pk)
    else:
        users = User.objects.filter(company=request.user.company)
        if request.user.role == 'manager':
            users = users.filter(
                branch_id=request.user.branch_id,
            ).exclude(role__in=('admin', 'ceo'))
        user = get_object_or_404(users, pk=pk)
    if request.method == 'POST':
        form = UserForm(request.POST, instance=user, actor=request.user)
        if form.is_valid():
            u = form.save(commit=False)
            if not request.user.is_superuser and request.user.company_id:
                u.company = request.user.company
            p = form.cleaned_data.get('password1')
            if p:
                u.set_password(p)
            u.save()
            messages.success(request, f'User {u.username} updated.')
            return redirect('core:users')
    else:
        form = UserForm(instance=user, actor=request.user)
    
    role_guide = [
        ('admin','Admin','Full access: users, settings, all data, all approvals'),
        ('manager','Manager','Finance, billing, approvals, reports, no system settings'),
        ('senior_officer','Senior Officer','All job cards, credentials, reports'),
        ('tax_officer','Tax Officer','Own job cards, clients, compliance filing'),
        ('receptionist','Receptionist','Client registration and walk-in intake only'),
    ]
    return render(request, 'core/user_form.html', {'form': form, 'title': f'Edit {user.username}', 'edit_user': user, 'role_guide': role_guide})


@login_required
def change_password(request):
    if request.method == 'POST':
        current  = request.POST.get('current_password', '')
        new1     = request.POST.get('new_password1', '')
        new2     = request.POST.get('new_password2', '')
        if not request.user.check_password(current):
            messages.error(request, 'Current password is incorrect.')
        elif not new1:
            messages.error(request, 'New password cannot be blank.')
        elif new1 != new2:
            messages.error(request, 'New passwords do not match.')
        elif len(new1) < 6:
            messages.error(request, 'Password must be at least 6 characters.')
        else:
            request.user.set_password(new1)
            request.user.save()
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Password changed successfully.')
            return redirect('core:settings')
    return redirect('core:settings')


@login_required
def user_settings(request):
    theme_guide = [
        ('ocean',    'Ocean Teal',    'A fresh cyan and teal palette inspired by coastal clarity.'),
        ('dark',     'Dark Mode',     'A polished night mode with luminous accents and deep contrast.'),
    ]
    company = getattr(request.user, 'company', None)
    can_manage_branches = company and request.user.is_manager_or_admin()
    can_add_users = _require_admin(request)
    BranchFormSet = inlineformset_factory(
        Company, Branch, form=BranchSettingsForm,
        extra=1, can_delete=False,
    )

    open_user_modal = False
    user_add_form = None
    if request.method == 'POST' and request.POST.get('settings_action') == 'add_user':
        if not can_add_users:
            messages.error(request, 'Admin access required.')
            return redirect('dashboard:index')
        user_add_form = UserForm(request.POST, actor=request.user)
        if user_add_form.is_valid():
            user, password = _save_new_user(user_add_form, request.user)
            messages.success(
                request,
                f'User "{user.username}" created. '
                f'Login: username = {user.username}, '
                f'password = {password}. '
                f'Ask them to change it after first login.'
            )
            return redirect('core:settings')
        open_user_modal = True
        user_form = UserSettingsForm(instance=request.user)
        company_form = CompanySettingsForm(instance=company) if company else None
        branch_formset = BranchFormSet(instance=company) if can_manage_branches else None
    elif request.method == 'POST':
        user_form = UserSettingsForm(request.POST, instance=request.user)
        company_form = CompanySettingsForm(request.POST, instance=company) if company else None
        branch_formset = BranchFormSet(
            request.POST, request.FILES, instance=company,
        ) if can_manage_branches else None
        if user_form.is_valid() and (company_form is None or company_form.is_valid()) and (branch_formset is None or branch_formset.is_valid()):
            user_form.save()
            if company_form:
                company_form.save()
            if branch_formset:
                branch_formset.save()
            messages.success(request, 'Your settings were updated.')
            return redirect('core:settings')
    else:
        user_form = UserSettingsForm(instance=request.user)
        company_form = CompanySettingsForm(instance=company) if company else None
        branch_formset = BranchFormSet(instance=company) if can_manage_branches else None

    if can_add_users and user_add_form is None:
        user_add_form = UserForm(actor=request.user)

    return render(request, 'core/settings.html', {
        'form': user_form,
        'company_form': company_form,
        'branch_formset': branch_formset,
        'can_manage_branches': can_manage_branches,
        'can_add_users': can_add_users,
        'user_add_form': user_add_form,
        'open_user_modal': open_user_modal,
        'theme_guide': theme_guide,
        'company': company,
    })


@login_required
@require_POST
def save_ui_theme(request):
    theme = request.POST.get('ui_theme') or request.POST.get('theme')
    valid = theme in dict(User.THEME_CHOICES)
    if not valid:
        return JsonResponse({'ok': False, 'error': 'Invalid theme selection.'}, status=400)

    request.user.ui_theme = theme
    request.user.save(update_fields=['ui_theme'])
    return JsonResponse({'ok': True, 'theme': theme})


@login_required
def _run_daily_now_unlocked(request):
    """Manually run all daily automation tasks immediately (Admin/Manager only)."""
    if not request.user.is_manager_or_admin():
        messages.error(request, 'Permission denied.')
        return redirect('dashboard:index')
    if request.method == 'POST':
        from core import jobs
        from django.utils import timezone
        from billing.models import Invoice
        results = []
        # 1. Mark overdue invoices
        updated = scope_queryset(request.user, Invoice.objects.filter(
            status__in=['sent', 'partially_paid'],
            due_date__lt=timezone.now().date()
        )).update(status='overdue')
        results.append(f'{updated} invoices marked overdue')
        # 2. Update client statuses
        try:
            jobs.update_client_statuses()
            results.append('client statuses updated')
        except Exception as e:
            results.append(f'client status error: {e}')
        # 3. Generate compliance deadlines
        try:
            jobs.generate_compliance_deadlines()
            results.append('compliance deadlines generated')
        except Exception as e:
            results.append(f'compliance error: {e}')
        # 4. Generate monthly job cards
        try:
            jobs.generate_monthly_jobcards()
            results.append('monthly job cards generated')
        except Exception as e:
            results.append(f'job card error: {e}')
        messages.success(request, 'Automation run complete: ' + ' | '.join(results))
    return redirect('dashboard:index')


@login_required
def run_daily_now(request):
    from core.automation_lock import automation_lock
    if request.method == 'POST':
        with automation_lock() as acquired:
            if not acquired:
                messages.warning(request, 'Another automation run is already in progress.')
                return redirect('dashboard:index')
            return _run_daily_now_unlocked(request)
    return _run_daily_now_unlocked(request)


@login_required
def trigger_automation(request):
    """Manually trigger automation tasks (Admin/Manager only)"""
    if not request.user.is_manager_or_admin():
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'generate_invoices':
            from core.automation import auto_generate_missing_invoices
            count = auto_generate_missing_invoices()
            return JsonResponse({
                'success': True,
                'message': f'Generated {count} missing invoices'
            })
        
        elif action == 'update_statuses':
            from django.core.management import call_command
            try:
                call_command('run_automation')
                return JsonResponse({
                    'success': True,
                    'message': 'Automation tasks completed successfully'
                })
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


# ============================================
# Export Handlers (Excel & PDF)
# ============================================

@login_required
def export_users_excel(request):
    """Export users list to Excel"""
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    users = _company_users(request).order_by('role', 'first_name')
    columns = ['Username', 'Full Name', 'Email', 'Role', 'Theme', 'WhatsApp', 'Status']
    data = []
    for u in users:
        data.append([
            u.username,
            u.get_full_name() or u.username,
            u.email,
            u.get_role_display(),
            u.get_ui_theme_display(),
            u.phone_whatsapp or '—',
            'Active' if u.is_active else 'Inactive',
        ])
    return export_to_excel('users', columns, data, title='Users Report')


@login_required
def export_users_pdf(request):
    """Export users list to PDF"""
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    
    users = _company_users(request).order_by('role', 'first_name')
    columns = ['Username', 'Full Name', 'Email', 'Role', 'WhatsApp', 'Status']
    data = []
    for u in users:
        data.append([
            u.username,
            u.get_full_name() or u.username,
            u.email,
            u.get_role_display(),
            u.phone_whatsapp or '—',
            'Active' if u.is_active else 'Inactive',
        ])
    return export_to_pdf('users', columns, data, title='Users Report')


@login_required
def export_clients_excel(request):
    """Export clients list to Excel"""
    from clients.models import Client
    
    clients = scope_queryset(request.user, Client.objects.select_related('assigned_officer'))
    q = request.GET.get('q', '')
    
    if q:
        from django.db.models import Q
        clients = clients.filter(
            Q(full_name__icontains=q) |
            Q(tin__icontains=q) |
            Q(phone_primary__icontains=q)
        )
    
    columns = ['Client ID', 'Full Name', 'TIN', 'Phone', 'Email', 'District', 'Status', 'Outstanding']
    data = []
    for c in clients[:1000]:  # Limit to 1000 rows for performance
        data.append([
            c.client_id,
            c.full_name,
            c.tin or '—',
            c.phone_primary,
            c.email or '—',
            c.district,
            c.get_status_display(),
            f"{c.total_outstanding:,.0f}" if c.total_outstanding else "0",
        ])
    return export_to_excel('clients', columns, data, title='Clients Report')


@login_required
def export_clients_pdf(request):
    """Export clients list to PDF"""
    from clients.models import Client
    
    clients = scope_queryset(
        request.user, Client.objects.select_related('assigned_officer'),
    )[:500]  # Limit for PDF
    columns = ['Client ID', 'Full Name', 'TIN', 'Phone', 'District', 'Status']
    data = []
    for c in clients:
        data.append([
            c.client_id,
            c.full_name,
            c.tin or '—',
            c.phone_primary,
            c.district,
            c.get_status_display(),
        ])
    return export_to_pdf('clients', columns, data, title='Clients Report')


@login_required
def export_invoices_excel(request):
    """Export invoices list to Excel"""
    from billing.models import Invoice
    
    invoices = scope_queryset(
        request.user, Invoice.objects.select_related('client'),
    ).order_by('-date_issued')
    columns = ['Invoice Number', 'Client', 'Amount', 'Paid', 'Outstanding', 'Status', 'Date']
    data = []
    for inv in invoices[:1000]:
        data.append([
            inv.invoice_number,
            inv.client.full_name if inv.client else '—',
            f"{inv.grand_total:,.0f}",
            f"{inv.amount_paid:,.0f}",
            f"{inv.balance_due:,.0f}",
            inv.get_status_display(),
            str(inv.date_issued),
        ])
    return export_to_excel('invoices', columns, data, title='Invoices Report')


@login_required
def export_invoices_pdf(request):
    """Export invoices list to PDF"""
    from billing.models import Invoice
    
    invoices = scope_queryset(
        request.user, Invoice.objects.select_related('client'),
    ).order_by('-date_issued')[:500]
    columns = ['Invoice', 'Client', 'Amount', 'Status', 'Date']
    data = []
    for inv in invoices:
        data.append([
            inv.invoice_number,
            inv.client.full_name if inv.client else '—',
            f"{inv.grand_total:,.0f}",
            inv.get_status_display(),
            str(inv.date_issued),
        ])
    return export_to_pdf('invoices', columns, data, title='Invoices Report')


@login_required
def export_jobcards_excel(request):
    """Export job cards list to Excel"""
    from services.models import JobCard
    from django.db.models import Q
    
    cards = scope_queryset(request.user, JobCard.objects.select_related('client', 'assigned_to'))
    status = request.GET.get('status', '')
    if status:
        cards = cards.filter(status=status)
    
    columns = ['Job Number', 'Client', 'Assigned To', 'Status', 'Created', 'Due Date', 'Total Fee']
    data = []
    for card in cards[:1000]:
        data.append([
            card.job_number,
            card.client.full_name if card.client else '—',
            card.assigned_to.get_full_name() if card.assigned_to else '—',
            card.get_status_display(),
            str(card.created_at.date()),
            str(card.due_date) if card.due_date else '—',
            f"{card.total_fee:,.0f}",
        ])
    return export_to_excel('jobcards', columns, data, title='Job Cards Report')


@login_required
def export_jobcards_pdf(request):
    """Export job cards list to PDF"""
    from services.models import JobCard
    
    cards = scope_queryset(
        request.user, JobCard.objects.select_related('client', 'assigned_to'),
    )[:500]
    columns = ['Job Number', 'Client', 'Status', 'Assigned To', 'Total Fee']
    data = []
    for card in cards:
        data.append([
            card.job_number,
            card.client.full_name if card.client else '—',
            card.get_status_display(),
            card.assigned_to.get_full_name() if card.assigned_to else '—',
            f"{card.total_fee:,.0f}",
        ])
    return export_to_pdf('jobcards', columns, data, title='Job Cards Report')


@login_required
def export_credentials_excel(request):
    """Export credentials list to Excel"""
    from credentials.models import ClientCredential
    
    creds = scope_queryset(
        request.user, ClientCredential.objects.select_related('client'),
        branch_path='client__branch',
    )
    columns = ['Credential Label', 'Client', 'Service', 'Created', 'Last Used']
    data = []
    for c in creds[:1000]:
        data.append([
            c.label,
            c.client.full_name if c.client else '—',
            c.service.name if c.service else '—',
            str(c.created_at.date()),
            str(c.last_used.date()) if c.last_used else '—',
        ])
    return export_to_excel('credentials', columns, data, title='Credentials Report')


@login_required
def export_credentials_pdf(request):
    """Export credentials list to PDF"""
    from credentials.models import ClientCredential
    
    creds = scope_queryset(
        request.user, ClientCredential.objects.select_related('client'),
        branch_path='client__branch',
    )[:500]
    columns = ['Credential Label', 'Client', 'Service', 'Created']
    data = []
    for c in creds:
        data.append([
            c.label,
            c.client.full_name if c.client else '—',
            c.service.name if c.service else '—',
            str(c.created_at.date()),
        ])
    return export_to_pdf('credentials', columns, data, title='Credentials Report')


@login_required
def export_deadlines_excel(request):
    """Export compliance deadlines list to Excel"""
    from compliance.models import ComplianceDeadline
    
    deadlines = scope_queryset(
        request.user,
        ComplianceDeadline.objects.select_related('obligation__client'),
        branch_path='obligation__client__branch',
    ).order_by('due_date')
    columns = ['Client', 'Obligation', 'Period', 'Due Date', 'Status', 'Priority']
    data = []
    for d in deadlines[:1000]:
        data.append([
            d.obligation.client.full_name if d.obligation and d.obligation.client else '—',
            d.obligation.name if d.obligation else '—',
            d.period_label,
            str(d.due_date),
            d.get_status_display(),
            d.get_priority_display() if hasattr(d, 'priority') else 'Normal',
        ])
    return export_to_excel('deadlines', columns, data, title='Compliance Deadlines Report')


@login_required
def export_deadlines_pdf(request):
    """Export compliance deadlines list to PDF"""
    from compliance.models import ComplianceDeadline
    
    deadlines = scope_queryset(
        request.user,
        ComplianceDeadline.objects.select_related('obligation__client'),
        branch_path='obligation__client__branch',
    ).order_by('due_date')[:500]
    columns = ['Client', 'Obligation', 'Period', 'Due Date', 'Status']
    data = []
    for d in deadlines:
        data.append([
            d.obligation.client.full_name if d.obligation and d.obligation.client else '—',
            d.obligation.name if d.obligation else '—',
            d.period_label,
            str(d.due_date),
            d.get_status_display(),
        ])
    return export_to_pdf('deadlines', columns, data, title='Compliance Deadlines Report')

