from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.http import JsonResponse
from .models import User
from django import forms


class UserForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput, required=False,
                                 help_text='Leave blank to keep existing password')
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'email_notify',
                  'phone_whatsapp', 'role', 'ui_theme', 'is_active_staff', 'is_active',
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


@login_required
def user_list(request):
    if not _require_admin(request):
        messages.error(request, 'Admin access required.')
        return redirect('dashboard:index')
    users = User.objects.all().order_by('role', 'first_name')
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
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            u = form.save(commit=False)
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
