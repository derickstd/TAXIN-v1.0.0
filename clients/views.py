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


def _generate_client_compliance_deadlines(client):
    """
    Generate compliance deadlines for a new client based on their obligations
    Returns count of deadlines created
    """
    from compliance.models import ComplianceObligation, ComplianceDeadline
    import calendar
    
    today = timezone.now().date()
    
    # If today is past the 15th, generate for next month; otherwise current month
    if today.day > 15:
        if today.month == 12:
            target_month = 1
            target_year = today.year + 1
        else:
            target_month = today.month + 1
            target_year = today.year
    else:
        target_month = today.month
        target_year = today.year
    
    # Period label is for the previous month (e.g., filing January returns in February)
    if target_month == 1:
        period_month = 12
        period_year = target_year - 1
    else:
        period_month = target_month - 1
        period_year = target_year
    
    period_label = f"{calendar.month_name[period_month]} {period_year}"
    
    # Create due date for 15th of target month
    try:
        due_date = today.replace(year=target_year, month=target_month, day=15)
    except ValueError:
        # Handle edge case if day doesn't exist in target month
        import datetime
        due_date = datetime.date(target_year, target_month, 15)
    
    # Get all active obligations for this client
    obligations = ComplianceObligation.objects.filter(
        client=client,
        is_active=True
    )
    
    created_count = 0
    
    for obligation in obligations:
        # Check if deadline already exists for this period
        deadline_exists = ComplianceDeadline.objects.filter(
            obligation=obligation,
            period_label=period_label
        ).exists()
        
        if not deadline_exists:
            ComplianceDeadline.objects.create(
                obligation=obligation,
                period_label=period_label,
                due_date=due_date,
                status='upcoming'
            )
            created_count += 1
    
    return created_count


def _client_onboarding_context(
    *,
    client_form=None,
    walkin_form=None,
    import_errors=None,
    import_created=0,
    import_section_active=None,
):
    from services.models import ServiceType
    import json
    
    # Get active service types for the service dropdown
    service_types = ServiceType.objects.filter(is_active=True).order_by('category', 'name')
    service_types_json = json.dumps([
        {'id': st.id, 'name': st.name, 'price': float(st.default_price)}
        for st in service_types
    ])
    
    return {
        'client_form': client_form or ClientForm(),
        'walkin_form': walkin_form or WalkInIntakeForm(),
        'districts': UGANDA_DISTRICTS,
        'import_errors': import_errors or [],
        'import_created': import_created,
        'import_section_active': import_section_active or 'new_client',
        'service_types_json': service_types_json,
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
        # Debug: Check what service fields are in POST
        service_fields = [key for key in request.POST.keys() if 'service' in key.lower()]
        print(f"\n=== DEBUG: Service fields in POST ===")
        print(f"Service fields found: {service_fields}")
        for field in service_fields:
            print(f"  {field} = {request.POST.get(field)}")
        print(f"=== END DEBUG ===")
        
        form = ClientForm(request.POST)
        if form.is_valid():
            from core.email_utils import send_welcome_email
            from credentials.models import ClientCredential
            from services.models import ClientServiceSubscription, ServiceType
            from cryptography.fernet import Fernet
            from django.conf import settings
            from decimal import Decimal
            
            client = form.save(commit=False)
            client.created_by = request.user
            # Handle district from POST directly since it's a free select
            client.district = request.POST.get('district', 'Kampala')
            client.save()
            
            # Process services and create obligations
            service_count = 0
            print(f"\n=== Processing services ===")
            for key in request.POST:
                if key.startswith('service_type_'):
                    index = key.split('_')[-1]
                    service_type_id = request.POST.get(f'service_type_{index}', '').strip()
                    price = request.POST.get(f'service_price_{index}', '').strip()
                    frequency = request.POST.get(f'service_frequency_{index}', 'monthly').strip()
                    
                    print(f"Found service: type_id={service_type_id}, price={price}, freq={frequency}")
                    
                    if service_type_id and price:
                        try:
                            from compliance.models import ComplianceObligation
                            
                            service_type = ServiceType.objects.get(pk=service_type_id)
                            print(f"  Service type found: {service_type.name}")
                            
                            # Create service subscription (no frequency field)
                            subscription = ClientServiceSubscription.objects.create(
                                client=client,
                                service_type=service_type,
                                negotiated_price=Decimal(price),
                                is_active=True
                            )
                            print(f"  Subscription created: {subscription.id}")
                            
                            # Create compliance obligation for this service
                            obligation, created = ComplianceObligation.objects.get_or_create(
                                client=client,
                                service_type=service_type,
                                defaults={
                                    'frequency': frequency,
                                    'is_active': True
                                }
                            )
                            print(f"  Obligation created: {obligation.id} (new={created})")
                            
                            service_count += 1
                        except ServiceType.DoesNotExist:
                            print(f"  ERROR: ServiceType {service_type_id} not found")
                        except ValueError as e:
                            print(f"  ERROR: ValueError - {e}")
                        except Exception as e:
                            print(f"  ERROR: {type(e).__name__} - {e}")
            print(f"Total services processed: {service_count}")
            print(f"=== End processing services ===")
            
            # Process credentials
            credential_count = 0
            
            for key in request.POST:
                if key.startswith('cred_platform_'):
                    index = key.split('_')[-1]
                    platform = request.POST.get(f'cred_platform_{index}', '').strip()
                    username = request.POST.get(f'cred_username_{index}', '').strip()
                    password = request.POST.get(f'cred_password_{index}', '').strip()
                    notes = request.POST.get(f'cred_notes_{index}', '').strip()
                    
                    if platform and username and password:
                        # Map platform to credential_type
                        platform_map = {
                            'URA': 'ura_etax',
                            'NSSF': 'nssf',
                            'URSB': 'ursb',
                            'ASYCUDA': 'customs',
                            'Other': 'custom'
                        }
                        
                        credential = ClientCredential(
                            client=client,
                            credential_type=platform_map.get(platform, 'custom'),
                            label=f"{platform} Login",
                            status='active',
                            created_by=request.user
                        )
                        credential.set_username(username)
                        credential.set_password(password)
                        if notes:
                            credential.set_notes(notes)
                        credential.save()
                        
                        credential_count += 1
            
            # Auto-generate compliance deadlines for current month
            compliance_count = _generate_client_compliance_deadlines(client)
            
            # Send welcome email
            email_sent = False
            if client.email:
                try:
                    send_welcome_email(client)
                    email_sent = True
                except:
                    pass
            
            # Build detailed success message
            success_msg = f'✅ Client registered successfully: {client.client_id} — {client.get_display_name()}'
            details = []
            if service_count > 0:
                details.append(f'{service_count} service(s) assigned')
            if credential_count > 0:
                details.append(f'{credential_count} credential(s) added')
            if compliance_count > 0:
                details.append(f'{compliance_count} compliance deadline(s) generated')
            if email_sent:
                details.append('welcome email sent')
            
            if details:
                success_msg += ' | ' + ' • '.join(details)
            
            messages.success(request, success_msg)
            
            # Redirect to client detail page
            return redirect('clients:detail', pk=client.pk)
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
            
            # If service_type is selected, use service name as purpose
            if intake.service_type and not intake.purpose:
                intake.purpose = intake.service_type.name
            
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
