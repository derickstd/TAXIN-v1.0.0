from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.hashers import make_password
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
            p = form.cleaned_data.get('password1')
            if p:
                user.set_password(p)
            else:
                user.set_password('taxman2025!')  # default
            user.save()
            messages.success(request, f'User {user.username} created. Default password: taxman2025!')
            return redirect('core:users')
    else:
        form = UserForm()
    role_guide = [
        ("admin","Admin","Full access: users, settings, all data, all approvals"),
        ("manager","Manager","Finance, billing, approvals, reports, no system settings"),
        ("senior_officer","Senior Officer","All job cards, credentials, reports"),
        ("tax_officer","Tax Officer","Own job cards, clients, compliance filing"),
        ("receptionist","Receptionist","Client registration and walk-in intake only"),
    ]
    return render(request, "core/user_form.html", {"form": form, "title": "New User", "is_new": True, "role_guide": role_guide})


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
def user_settings(request):
    theme_guide = [
        ('classic', 'Classic Blue', 'The existing Taxman256 look with strong blue navigation and gold accents.'),
        ('forest', 'Forest Ledger', 'A calmer green-led palette suited for long working sessions.'),
        ('sunset', 'Sunset Copper', 'A warmer orange and navy mix with softer surfaces.'),
        ('midnight', 'Midnight Slate', 'A deeper slate theme with cooler contrast for focused work.'),
        ('dark', 'Dark Mode', 'A true dark interface with higher contrast surfaces for low-light work.'),
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
