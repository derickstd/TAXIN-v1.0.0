from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.http import JsonResponse
import logging
from .models import User, Company, AuditLog
from django import forms
from django.utils.text import slugify
from .export_utils import export_to_excel, export_to_pdf, paginate_list


class UserForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput, required=False,
                                 help_text='Leave blank to keep existing password')
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'email_notify',
                  'phone_whatsapp', 'company', 'role', 'ui_theme', 'is_active_staff', 'is_active',
                  'receive_debt_alerts', 'receive_task_reminders', 'date_joined_firm']
        widgets = {'date_joined_firm': forms.DateInput(attrs={'type': 'date'})}

    def clean(self):
        cd = super().clean()
        p1, p2 = cd.get('password1'), cd.get('password2')
        if p1 or p2:
            if p1 != p2:
                raise forms.ValidationError('Passwords do not match.')
        return cd


class UserSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'email_notify', 'phone_whatsapp',
            'receive_debt_alerts', 'receive_task_reminders', 'ui_theme',
        ]


class CompanySignupForm(forms.Form):
    company_name = forms.CharField(label='Company Name', max_length=255)
    slug = forms.SlugField(label='Company Slug', max_length=255, required=False,
                           help_text='Unique URL-friendly identifier for your company.')
    registration_number = forms.CharField(label='Registration Number', max_length=100, required=False)
    tin = forms.CharField(label='TIN', max_length=100, required=False)
    company_email = forms.EmailField(label='Company Email', required=False)
    company_phone = forms.CharField(label='Company Phone', max_length=20, required=False)
    company_address = forms.CharField(label='Company Address', widget=forms.Textarea(attrs={'rows': 3}), required=False)
    create_database = forms.BooleanField(label='Create company database', required=False, initial=True,
                                         help_text='Create a dedicated sqlite database file for this company and run migrations.')

    username = forms.CharField(label='Admin Username', max_length=150)
    first_name = forms.CharField(label='First Name', max_length=150)
    last_name = forms.CharField(label='Last Name', max_length=150, required=False)
    email = forms.EmailField(label='Admin Email')
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                existing_classes = field.widget.attrs.get('class', '')
                field.widget.attrs['class'] = (existing_classes + ' form-ctrl').strip()

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')
        if password1 and password1 != password2:
            raise forms.ValidationError('Passwords do not match.')
        return cleaned

    def clean_slug(self):
        slug = self.cleaned_data.get('slug') or slugify(self.cleaned_data.get('company_name', ''))
        if Company.objects.filter(slug=slug).exists():
            raise forms.ValidationError('That company slug is already registered. Please choose another.')
        return slug

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Username already exists. Choose another username.')
        return username


def _create_company_database(company, changed_by=None):
    import os
    from django.conf import settings
    from django.core.management import call_command

    logger = logging.getLogger(__name__)
    db_dir = os.path.join(settings.BASE_DIR, 'company_databases')
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, f"{company.slug}.sqlite3")
    alias = f'company_{company.slug}'
    settings.DATABASES[alias] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': db_path,
        'ATOMIC_REQUESTS': False,
    }
    logger.info('Creating tenant DB for company %s at %s (alias=%s)', company.slug, db_path, alias)
    call_command('migrate', database=alias, interactive=False, verbosity=0)
    company.db_name = alias
    company.save(update_fields=['db_name'])

    # Record an audit log so admins can notice tenant creation
    try:
        AuditLog.objects.create(
            model_name='company',
            object_id=str(company.pk),
            action='UPDATE',
            changed_fields={'db_name': alias},
            changed_by=changed_by,
            notes=f'Created tenant database {alias} at {db_path}'
        )
    except Exception:
        logger.exception('Failed to record AuditLog for company DB creation: %s', company.slug)

    return alias


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
    return request.user.is_authenticated and (request.user.role in ('admin', 'manager') or request.user.is_superuser)


def _company_users(request):
    if request.user.is_superuser:
        return User.objects.all()
    if request.user.company_id:
        return User.objects.filter(company=request.user.company)
    return User.objects.none()


def signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')
    if request.method == 'POST':
        form = CompanySignupForm(request.POST)
        if form.is_valid():
            slug = form.cleaned_data['slug']
            company = Company.objects.create(
                name=form.cleaned_data['company_name'],
                slug=slug,
                registration_number=form.cleaned_data['registration_number'],
                tin=form.cleaned_data['tin'],
                email=form.cleaned_data['company_email'],
                phone=form.cleaned_data['company_phone'],
                address=form.cleaned_data['company_address'],
                active=True,
            )
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password1'],
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                company=company,
                role='admin',
                is_active=True,
                is_active_staff=True,
            )
            company.owner = user
            company.save()
            # Record company creation in audit log for admin visibility
            try:
                AuditLog.objects.create(
                    model_name='company',
                    object_id=str(company.pk),
                    action='CREATE',
                    changed_fields={'name': company.name, 'slug': company.slug},
                    changed_by=user,
                    notes='Company registered via signup form'
                )
            except Exception:
                logging.getLogger(__name__).exception('Failed to create AuditLog for new company %s', company.slug)
            # Optionally create a dedicated sqlite DB for this company and run migrations
            if form.cleaned_data.get('create_database'):
                try:
                    _create_company_database(company, changed_by=user)
                except Exception as e:
                    import logging
                    logging.exception('Error creating company DB for %s: %s', company.slug, e)
                    messages.error(request,
                        'The company account was created, but the dedicated database could not be created automatically. '
                        'Please contact the system administrator or try again later.')
                    return render(request, 'core/signup.html', {'form': form})
            messages.success(request, 'Company created successfully. You can now log in.')
            return redirect('login')
        else:
            messages.error(request, 'Please correct the highlighted fields before continuing.')
            for name in form.errors:
                if name in form.fields:
                    existing = form.fields[name].widget.attrs.get('class', '')
                    if 'err' not in existing:
                        form.fields[name].widget.attrs['class'] = (existing + ' err').strip()
    else:
        form = CompanySignupForm()
    return render(request, 'core/signup.html', {'form': form})


@login_required
def user_list(request):
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    users = _company_users(request).order_by('role', 'first_name')
    return render(request, 'core/user_list.html', {'users': users})


@login_required
def user_create(request):
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            if not request.user.is_superuser and request.user.company_id:
                user.company = request.user.company
            p = form.cleaned_data.get('password1') or 'taxman2025!'
            user.set_password(p)
            user.is_active = True
            user.is_active_staff = True
            user.save()
            messages.success(
                request,
                f'User "{user.username}" created. '
                f'Login: username = {user.username}, '
                f'password = {p}. '
                f'Ask them to change it after first login.'
            )
            return redirect('core:users')
    else:
        form = UserForm()
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


@login_required
def user_edit(request, pk):
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    if request.user.is_superuser:
        user = get_object_or_404(User, pk=pk)
    else:
        user = get_object_or_404(User, pk=pk, company=request.user.company)
    if request.method == 'POST':
        form = UserForm(request.POST, instance=user)
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
        form = UserForm(instance=user)
    
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
    if request.method == 'POST':
        form = UserSettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your settings were updated.')
            return redirect('core:settings')
    else:
        form = UserSettingsForm(instance=request.user)
    return render(request, 'core/settings.html', {
        'form': form,
        'theme_guide': theme_guide,
    })


@login_required
def run_daily_now(request):
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
        updated = Invoice.objects.filter(
            status__in=['sent', 'partially_paid'],
            due_date__lt=timezone.now().date()
        ).update(status='overdue')
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
    
    clients = Client.objects.select_related('assigned_officer').all()
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
    
    clients = Client.objects.select_related('assigned_officer').all()[:500]  # Limit for PDF
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
    
    invoices = Invoice.objects.select_related('client').all().order_by('-date_issued')
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
    
    invoices = Invoice.objects.select_related('client').all().order_by('-date_issued')[:500]
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
    
    cards = JobCard.objects.select_related('client', 'assigned_to').all()
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
    
    cards = JobCard.objects.select_related('client', 'assigned_to').all()[:500]
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
    
    creds = ClientCredential.objects.select_related('client').all()
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
    
    creds = ClientCredential.objects.select_related('client').all()[:500]
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
    
    deadlines = ComplianceDeadline.objects.select_related('obligation__client').all().order_by('due_date')
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
    
    deadlines = ComplianceDeadline.objects.select_related('obligation__client').all().order_by('due_date')[:500]
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

