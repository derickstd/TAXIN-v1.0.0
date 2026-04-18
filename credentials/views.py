from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.db.models import Q
from .models import ClientCredential, CredentialAccessLog
from clients.models import Client
from django import forms

class CredentialForm(forms.ModelForm):
    username_plain = forms.CharField(label='Username / TIN', required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Username or TIN', 'autocomplete': 'off'}))
    password_plain = forms.CharField(label='Password', required=False,
        widget=forms.PasswordInput(attrs={'placeholder': 'Enter password', 'autocomplete': 'new-password'}))
    notes_plain = forms.CharField(label='Notes (encrypted)', required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Security question, recovery email, PIN…'}))

    class Meta:
        model = ClientCredential
        fields = ['client', 'credential_type', 'label', 'status', 'expiry_date']
        widgets = {'expiry_date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.order_by('full_name')
        self.fields['expiry_date'].required = False


@login_required
def credential_list(request):
    q = request.GET.get('q', '')
    type_filter = request.GET.get('type', '')
    creds = ClientCredential.objects.select_related('client', 'last_accessed_by').order_by('client__full_name')
    if q:
        creds = creds.filter(Q(client__full_name__icontains=q) | Q(client__trading_name__icontains=q) | Q(label__icontains=q))
    if type_filter:
        creds = creds.filter(credential_type=type_filter)
    today = timezone.now().date()
    expiring_soon = creds.filter(expiry_date__lte=today + timezone.timedelta(days=14), expiry_date__gte=today)
    return render(request, 'credentials/credential_list.html', {
        'creds': creds, 'expiring_soon': expiring_soon,
        'today': today, 'q': q, 'type_filter': type_filter,
        'cred_types': ClientCredential.CRED_TYPE,
    })


@login_required
def credential_create(request):
    if request.method == 'POST':
        form = CredentialForm(request.POST)
        if form.is_valid():
            cred = form.save(commit=False)
            cred.created_by = request.user
            cred.set_username(form.cleaned_data.get('username_plain', ''))
            cred.set_password(form.cleaned_data.get('password_plain', ''))
            cred.set_notes(form.cleaned_data.get('notes_plain', ''))
            cred.save()
            messages.success(request, 'Credential saved and encrypted successfully.')
            return redirect('credentials:list')
    else:
        client_id = request.GET.get('client')
        form = CredentialForm(initial={'client': client_id} if client_id else {})
    return render(request, 'credentials/credential_form.html', {'form': form})


@login_required
def credential_edit(request, pk):
    cred = get_object_or_404(ClientCredential, pk=pk)
    if request.method == 'POST':
        form = CredentialForm(request.POST, instance=cred)
        if form.is_valid():
            c = form.save(commit=False)
            pw = form.cleaned_data.get('password_plain', '')
            un = form.cleaned_data.get('username_plain', '')
            notes = form.cleaned_data.get('notes_plain', '')
            if un: c.set_username(un)
            if pw: c.set_password(pw)
            if notes: c.set_notes(notes)
            c.save()
            messages.success(request, 'Credential updated successfully.')
            return redirect('credentials:list')
    else:
        form = CredentialForm(instance=cred)
    return render(request, 'credentials/credential_form.html', {'form': form, 'edit': True, 'cred': cred})


@login_required
def reveal_password(request, pk):
    cred = get_object_or_404(ClientCredential, pk=pk)
    CredentialAccessLog.objects.create(credential=cred, accessed_by=request.user)
    cred.last_accessed_by = request.user
    cred.last_accessed_at = timezone.now()
    cred.save(update_fields=['last_accessed_by', 'last_accessed_at'])
    return JsonResponse({
        'username': cred.get_username(),
        'password': cred.get_password(),
        'notes':    cred.get_notes(),
    })
