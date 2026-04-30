from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from django.utils import timezone
from .models import Client, WalkInIntake
from .forms import ClientForm, WalkInIntakeForm
from billing.models import Invoice

UGANDA_DISTRICTS = [
    'Kampala','Wakiso','Mukono','Jinja','Gulu','Mbarara','Masaka','Mbale',
    'Lira','Arua','Fort Portal','Hoima','Soroti','Kabale','Tororo','Entebbe',
    'Iganga','Bugiri','Busia','Malaba','Eldoret (Kenya)','Other',
]


def _client_onboarding_context(
    *,
    client_form=None,
    walkin_form=None,
    import_errors=None,
    import_created=0,
    import_section_active=None,
):
    return {
        'client_form': client_form or ClientForm(),
        'walkin_form': walkin_form or WalkInIntakeForm(),
        'districts': UGANDA_DISTRICTS,
        'import_errors': import_errors or [],
        'import_created': import_created,
        'import_section_active': import_section_active or 'new_client',
    }


def _render_client_onboarding(request, **kwargs):
    return render(request, 'clients/client_onboarding.html', _client_onboarding_context(**kwargs))


def _process_client_import_file(uploaded_file, user):
    import csv
    import io

    text = uploaded_file.read().decode('utf-8-sig', errors='ignore')
    reader = csv.DictReader(io.StringIO(text))
    created = 0
    errors = []
    for i, row in enumerate(reader, 1):
        try:
            name = (row.get('full_name') or row.get('name') or '').strip()
            phone = (row.get('phone_primary') or row.get('phone') or '').strip()
            if not name or not phone:
                errors.append(f"Row {i}: missing name or phone")
                continue
            if Client.objects.filter(phone_primary=phone).exists():
                errors.append(f"Row {i}: {name} — phone already exists, skipped")
                continue
            Client.objects.create(
                full_name=name,
                tin=(row.get('tin') or '').strip(),
                phone_primary=phone,
                phone_whatsapp=(row.get('phone_whatsapp') or phone).strip(),
                email=(row.get('email') or '').strip(),
                district=(row.get('district') or 'Kampala').strip(),
                physical_address=(row.get('address') or '').strip(),
                client_type=(row.get('client_type') or 'individual').strip().lower(),
                assigned_officer=user,
                created_by=user,
            )
            created += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")
    return created, errors

@login_required
def client_list(request):
    clients = Client.objects.select_related('assigned_officer').all()
    q = request.GET.get('q','')
    status = request.GET.get('status','')
    ctype = request.GET.get('type','')
    if q:
        clients = clients.filter(
            Q(full_name__icontains=q)|
            Q(tin__icontains=q)|Q(phone_primary__icontains=q)|Q(client_id__icontains=q)
        )
    if status:
        clients = clients.filter(status=status)
    if ctype:
        clients = clients.filter(client_type=ctype)
    if request.headers.get("HX-Request"):
        return render(request, 'clients/partials/client_rows.html', {'clients': clients})
    total_outstanding = clients.aggregate(s=Sum('total_outstanding'))['s'] or 0
    return render(request, 'clients/client_list.html', {
        'clients': clients, 'q': q, 'status': status, 'ctype': ctype,
        'status_choices': Client.STATUS, 'type_choices': Client.CLIENT_TYPE,
        'total_outstanding': total_outstanding,
        'counts': {s: Client.objects.filter(status=s).count() for s,_ in Client.STATUS},
    })

@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    job_cards = client.job_cards.prefetch_related('line_items').order_by('-created_at')[:20]
    invoices = client.invoices.order_by('-date_issued')[:20]
    total_invoiced = client.invoices.aggregate(s=Sum('grand_total'))['s'] or 0
    total_paid = client.invoices.aggregate(s=Sum('amount_paid'))['s'] or 0
    walkins = client.walkin_intakes.order_by('-visit_date')[:5]
    from credentials.models import ClientCredential
    from compliance.models import ComplianceObligation
    creds_count = ClientCredential.objects.filter(client=client).count()
    obligations = ComplianceObligation.objects.filter(client=client, is_active=True).select_related('service_type')
    details = [
        ('Full Name', client.full_name),
        ('TIN', client.tin or 'Not provided'),
        ('Phone', client.phone_primary),
        ('WhatsApp', client.phone_whatsapp or 'Same as phone'),
        ('Email', client.email or '—'),
        ('District', client.district),
        ('Address', client.physical_address or '—'),
        ('Officer', client.assigned_officer.get_full_name() if client.assigned_officer else '—'),
        ('Registered', str(client.date_registered)),
        ('Referred By', client.referred_by.get_display_name() if client.referred_by else '—'),
    ]
    return render(request, 'clients/client_detail.html', {
        'client': client, 'job_cards': job_cards, 'invoices': invoices,
        'total_invoiced': total_invoiced, 'total_paid': total_paid,
        'balance': total_invoiced - total_paid,
        'walkins': walkins, 'creds_count': creds_count,
        'obligations': obligations, 'details': details,
    })

@login_required
def client_create(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            from core.email_utils import send_welcome_email
            
            client = form.save(commit=False)
            client.created_by = request.user
            # Handle district from POST directly since it's a free select
            client.district = request.POST.get('district', 'Kampala')
            client.save()
            
            # Send welcome email
            if client.email:
                send_welcome_email(client)
            
            messages.success(request, f'Client {client.client_id} — {client.get_display_name()} created.')
            # Redirect to walk-in intake with the new client pre-selected
            return redirect(f"{request.path}?section=walkin&client={client.pk}")
        return _render_client_onboarding(
            request,
            client_form=form,
            import_section_active='new_client',
        )
    form = ClientForm()
    section = request.GET.get('section', 'new_client')
    client_id = request.GET.get('client')
    walkin_form = WalkInIntakeForm(initial={'client': client_id} if client_id else {})
    return _render_client_onboarding(
        request, 
        client_form=form, 
        walkin_form=walkin_form,
        import_section_active=section
    )

@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            c = form.save(commit=False)
            c.district = request.POST.get('district', client.district)
            c.save()
            messages.success(request, 'Client updated successfully.')
            return redirect('clients:detail', pk=client.pk)
    else:
        form = ClientForm(instance=client)
    return render(request, 'clients/client_form.html', {
        'form': form, 'title': f'Edit — {client.get_display_name()}',
        'client': client, 'districts': UGANDA_DISTRICTS,
    })

@login_required
def walkin_create(request):
    if request.method == 'POST':
        form = WalkInIntakeForm(request.POST)
        if form.is_valid():
            intake = form.save(commit=False)
            intake.assigned_staff = form.cleaned_data.get('assigned_staff') or request.user
            intake.save()
            messages.success(request, f'Walk-in recorded for {intake.client.get_display_name()}.')
            return redirect('clients:detail', pk=intake.client.pk)
        return _render_client_onboarding(
            request,
            walkin_form=form,
            import_section_active='walkin',
        )
    client_id = request.GET.get('client')
    form = WalkInIntakeForm(initial={'client': client_id} if client_id else {})
    return _render_client_onboarding(request, walkin_form=form, import_section_active='walkin')

@login_required
def client_search_api(request):
    q = request.GET.get('q','')
    clients = Client.objects.filter(
        Q(full_name__icontains=q)|
        Q(tin__icontains=q)|Q(client_id__icontains=q)
    )[:10] if q else []
    return render(request, 'clients/partials/search_results.html', {'clients': clients})


@login_required
def client_import(request):
    """Batch import clients from CSV."""
    if request.method == 'POST' and request.FILES.get('csv_file'):
        created, errors = _process_client_import_file(request.FILES['csv_file'], request.user)
        if created:
            messages.success(request, f'✅ Successfully imported {created} client(s).')
        for err in errors[:5]:
            messages.warning(request, err)
        return redirect('clients:list')
    if request.method == 'POST':
        messages.error(request, 'Please choose a CSV file to import.')
        return _render_client_onboarding(
            request,
            import_errors=['Please choose a CSV file before importing.'],
            import_section_active='batch_import',
        )
    return _render_client_onboarding(request, import_section_active='batch_import')
