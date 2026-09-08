from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.db.models import Q
from .models import ClientCredential, CredentialAccessLog
from clients.models import Client
from django import forms
from django.conf import settings
from django.db import transaction

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
        else:
            messages.error(request, 'Please fix the errors below.')
        return redirect('credentials:list')

    q = request.GET.get('q', '')
    type_filter = request.GET.get('type', '')
    client_filter = request.GET.get('client', '')
    creds = ClientCredential.objects.select_related('client', 'last_accessed_by').order_by('client__full_name')
    if q:
        creds = creds.filter(Q(client__full_name__icontains=q) | Q(label__icontains=q))
    if type_filter:
        creds = creds.filter(credential_type=type_filter)
    if client_filter:
        creds = creds.filter(client__pk=client_filter)
    today = timezone.now().date()
    expiring_soon = creds.filter(expiry_date__lte=today + timezone.timedelta(days=14), expiry_date__gte=today)
    filtered_client = None
    if client_filter:
        filtered_client = Client.objects.filter(pk=client_filter).first()
    from core.utils import paginate_queryset
    page_obj = paginate_queryset(request, creds.order_by('client__full_name'), per_page=25)
    search_records = [
        {
            'client': credential.client.get_display_name(),
            'type': credential.get_credential_type_display(),
            'label': credential.label,
            'status': credential.get_status_display(),
            'expiry': credential.expiry_date.isoformat() if credential.expiry_date else '',
            'url': f'/clients/{credential.client_id}/',
        }
        for credential in creds
    ]
    return render(request, 'credentials/credential_list.html', {
        'creds': page_obj, 'page_obj': page_obj, 'expiring_soon': expiring_soon,
        'today': today, 'q': q, 'type_filter': type_filter,
        'cred_types': ClientCredential.CRED_TYPE,
        'add_form': CredentialForm(),
        'filtered_client': filtered_client,
        'google_sheet_edit_url': settings.GOOGLE_SHEET_EDIT_URL,
        'search_records': search_records,
    })


@login_required
def google_sheet_sync(request):
    from .google_sheets import credential_rows, parse_date, read_rows, write_rows

    try:
        if request.method == 'POST' and request.POST.get('direction') == 'to_sheet':
            credentials = ClientCredential.objects.select_related('client').order_by('pk')
            write_rows(credential_rows(credentials))
            messages.success(request, 'System credentials were written to Google Sheets.')
        elif request.method == 'POST' and request.POST.get('direction') == 'from_sheet':
            _, headers, rows = read_rows()
            required_headers = {'System ID', 'Client ID', 'Label', 'Username', 'Password', 'Status'}
            if not required_headers.issubset(set(headers)):
                messages.error(
                    request,
                    'Google Sheet layout is not a credential register yet. '
                    'Push System Changes once after backing up the current sheet, then pull changes.',
                )
                return redirect('credentials:list')
            updated = 0
            skipped = 0
            with transaction.atomic():
                for row in rows:
                    try:
                        credential = ClientCredential.objects.select_related('client').get(pk=int(row.get('System ID', '')))
                        username = row.get('Username', '')
                        password = row.get('Password', '')
                        notes = row.get('Notes', '')
                        if username:
                            credential.set_username(username)
                        if password:
                            credential.set_password(password)
                        if notes:
                            credential.set_notes(notes)
                        credential.label = row.get('Label') or credential.label
                        credential.status = row.get('Status') or credential.status
                        credential.expiry_date = parse_date(row.get('Expiry Date', ''))
                        credential.save()
                        updated += 1
                    except (ValueError, ClientCredential.DoesNotExist):
                        skipped += 1
            messages.success(request, f'Google Sheets changes imported: {updated} updated, {skipped} skipped.')
        else:
            messages.error(request, 'Choose a valid Google Sheets sync direction.')
    except Exception as exc:
        messages.error(request, f'Google Sheets sync failed: {exc}')
    return redirect('credentials:list')



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
