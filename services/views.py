from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal
from .models import JobCard, JobCardLineItem, ServiceType, StaffActivityLog, TimeEntry
from .forms import JobCardForm, LineItemFormSet, ServiceTypeForm
import calendar as cal
from core.utils import paginate_queryset
from clients.models import Client


def _auto_log_time(job, user, description, hours=Decimal('0.25')):
    """Auto-log time entry for any staff action. Date and hours are automatic."""
    TimeEntry.objects.create(
        job_card=job,
        staff=user,
        description=description,
        hours=hours,
        entry_date=timezone.now().date(),
    )


def _line_item_has_content(item):
    return any([
        item.service_type_id,
        (item.custom_description or '').strip(),
        (item.period_label or '').strip(),
        (item.notes or '').strip(),
        item.default_price not in (None, ''),
        item.negotiated_price not in (None, ''),
    ])


def _can_manage_services(user):
    return user.is_superuser or user.is_manager_or_admin()


def _service_catalogue_context(request, service_form=None, open_add_modal=False):
    services = ServiceType.objects.all().order_by('category', 'name') if _can_manage_services(request.user) else ServiceType.objects.filter(is_active=True).order_by('category', 'name')
    return {
        'services': services,
        'can_manage_services': _can_manage_services(request.user),
        'service_form': service_form or ServiceTypeForm(),
        'open_add_modal': open_add_modal,
    }

@login_required
def jobcard_list(request):
    all_jobs_qs = JobCard.objects.select_related('client','assigned_to').prefetch_related('line_items').all()
    status = request.GET.get('status','')
    q = request.GET.get('q','')
    jobs_qs = all_jobs_qs
    if status: jobs_qs = jobs_qs.filter(status=status)
    if q:
        jobs_qs = jobs_qs.filter(Q(job_number__icontains=q) | Q(client__full_name__icontains=q))
    kanban_cols = [(s, label, list(all_jobs_qs.filter(status=s))) for s, label in JobCard.STATUS]
    page_obj = paginate_queryset(request, jobs_qs.order_by('-created_at'), per_page=25)
    return render(request, 'services/jobcard_list.html', {
        'jobs': page_obj, 'page_obj': page_obj, 'kanban_cols': kanban_cols, 'status': status, 'q': q,
        'status_choices': JobCard.STATUS, 'today': timezone.now().date(),
    })

@login_required
def jobcard_detail(request, pk):
    job = get_object_or_404(JobCard, pk=pk)
    logs = job.activity_logs.select_related('staff').all()
    time_entries = job.time_entries.select_related('staff').all()
    total_hours = sum(t.hours for t in time_entries)
    return render(request, 'services/jobcard_detail.html', {
        'job': job, 'logs': logs,
        'time_entries': time_entries, 'total_hours': total_hours,
        'today': timezone.now().date(),
    })

@login_required
def jobcard_create(request):
    today = timezone.now()
    years = list(range(today.year - 1, today.year + 3))
    from core.models import User
    default_officer = User.objects.filter(role='tax_officer', is_active=True).first()

    if request.method == 'POST':
        form = JobCardForm(request.POST)
        formset = LineItemFormSet(request.POST)
        intake_pk = request.POST.get('walkin_intake_pk')
        from_walkin = bool(intake_pk) or bool(request.POST.get('new_job_reg'))

        # Before creating, check for similar existing transactions to avoid duplicates
        from core.duplicate_detection import check_duplicate_transaction
        period_month = request.POST.get('period_month') or request.POST.get('period_month')
        period_year = request.POST.get('period_year') or request.POST.get('period_year')
        svc_id = request.POST.get('jobcardlineitem_set-0-service_type')
        svc = ServiceType.objects.filter(pk=svc_id).first() if svc_id else None
        similar = check_duplicate_transaction(
            client=Client.objects.filter(pk=request.POST.get('client')).first(),
            service_type=svc,
            period_year=period_year and int(period_year) or None,
            period_month=period_month and int(period_month) or None,
            within_days=14,
        )
        if similar:
            # allow force-create via POST param
            if request.POST.get('force_create') == '1':
                pass
            else:
                return render(request, 'services/duplicate_transaction.html', {
                    'similar': similar,
                    'form': form,
                    'formset': formset,
                    'orig_post': request.POST,
                })

        if form.is_valid() and (formset.is_valid() or from_walkin):
            job = form.save(commit=False)
            job.created_by = request.user
            job.save()

            if from_walkin:
                # Build line item directly from POST — ignore formset validation entirely
                svc_id = request.POST.get('jobcardlineitem_set-0-service_type')
                price_raw = request.POST.get('jobcardlineitem_set-0-negotiated_price', '0')
                default_raw = request.POST.get('jobcardlineitem_set-0-default_price', '0')
                try:
                    price = Decimal(price_raw) if price_raw else Decimal('0')
                except Exception:
                    price = Decimal('0')
                try:
                    default_price = Decimal(default_raw) if default_raw else Decimal('0')
                except Exception:
                    default_price = Decimal('0')
                svc = None
                if svc_id:
                    svc = ServiceType.objects.filter(pk=svc_id).first()
                vat = price * Decimal('0.18') if svc and svc.vat_applicable else Decimal('0')
                JobCardLineItem.objects.create(
                    job_card=job,
                    service_type=svc,
                    custom_description='' if svc else request.POST.get('jobcardlineitem_set-0-custom_description', 'Walk-in visit'),
                    default_price=default_price or (svc.default_price if svc else Decimal('0')),
                    negotiated_price=price,
                    vat_amount=vat,
                    status='not_handled',
                    period_label=request.POST.get('jobcardlineitem_set-0-period_label', ''),
                    notes=request.POST.get('jobcardlineitem_set-0-notes', ''),
                )
            else:
                formset.instance = job
                items = formset.save(commit=False)
                for item in items:
                    if not _line_item_has_content(item):
                        continue
                    if item.service_type and not item.default_price:
                        item.default_price = item.service_type.default_price
                    item.default_price = item.default_price or Decimal('0')
                    if not item.negotiated_price:
                        item.negotiated_price = item.default_price or Decimal('0')
                    if item.service_type and item.service_type.vat_applicable:
                        item.vat_amount = item.negotiated_price * Decimal('0.18')
                    else:
                        item.vat_amount = Decimal('0')
                    item.save()
                for obj in formset.deleted_objects:
                    obj.delete()

            job.update_total()
            create_invoice = request.POST.get('create_invoice', 'yes') == 'yes'
            invoice = None
            if create_invoice:
                invoice = _auto_create_invoice(job, request.user)
            # If payment was received at point of job creation, record it now
            # The billing signal cascades: updates invoice status, job card line items,
            # client outstanding balance — all automatically
            if invoice and request.POST.get('payment_received') == 'yes':
                from billing.models import Payment
                price_raw = request.POST.get('jobcardlineitem_set-0-negotiated_price', '0')
                try:
                    full_amount = Decimal(price_raw) if price_raw else invoice.grand_total
                except Exception:
                    full_amount = invoice.grand_total
                pay_raw = request.POST.get('payment_amount', '').strip()
                try:
                    pay_amount = Decimal(pay_raw) if pay_raw else full_amount
                except Exception:
                    pay_amount = full_amount
                pay_amount = min(max(pay_amount, Decimal('0')), invoice.grand_total)
                if pay_amount > 0:
                    Payment.objects.create(
                        invoice=invoice,
                        amount=pay_amount,
                        method=request.POST.get('payment_method', 'cash'),
                        reference=request.POST.get('payment_reference', ''),
                        received_by=request.user,
                        notes='Payment recorded at job card creation',
                    )
            StaffActivityLog.objects.create(job_card=job, staff=request.user, action='Job card created')
            _auto_log_time(job, request.user, 'Job card created', Decimal('0.25'))
            if intake_pk:
                from clients.models import WalkInIntake
                WalkInIntake.objects.filter(pk=intake_pk).update(outcome='job_created')
            inv_msg = f'Invoice {invoice.invoice_number} auto-generated.' if invoice else 'No invoice created (skipped by user).'
            messages.success(request, f'Job card {job.job_number} created. {inv_msg}')
            return redirect('services:detail', pk=job.pk)
        else:
            messages.error(request, 'Please fix the errors below.')
    else:
        client_id = request.GET.get('client')
        initial = {}
        if client_id:
            initial['client'] = client_id
        initial['period_month'] = today.month
        initial['period_year'] = today.year
        form = JobCardForm(initial=initial)
        formset = LineItemFormSet()

    return render(request, 'services/jobcard_form.html', {
        'form': form, 'formset': formset, 'title': 'New Job Card',
        'years': years, 'current_year': today.year,
        'default_officer': default_officer,
    })

def _auto_create_invoice(job, user):
    from billing.models import Invoice
    if hasattr(job, 'invoice'):
        return None
    subtotal = sum(li.negotiated_price for li in job.line_items.all())
    vat_total = sum(li.vat_amount for li in job.line_items.all())
    due = job.due_date or (timezone.now().date() + timezone.timedelta(days=14))
    return Invoice.objects.create(
        client=job.client, job_card=job, due_date=due,
        subtotal=subtotal, vat_total=vat_total, grand_total=subtotal + vat_total,
        status='sent' if subtotal > 0 else 'draft', created_by=user,
    )

@login_required
def update_line_status(request, pk):
    item = get_object_or_404(JobCardLineItem, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(JobCardLineItem.ITEM_STATUS):
            item.status = new_status
            item.save()
            StaffActivityLog.objects.create(
                job_card=item.job_card, staff=request.user,
                action=f'"{item.get_description()}" → {item.get_status_display()}'
            )
            _auto_log_time(
                item.job_card, request.user,
                f'{item.get_description()} — marked {item.get_status_display()}',
                Decimal('0.25'),
            )
            job = item.job_card
            
            # Auto-update job card status based on line items
            all_items = list(job.line_items.all())
            if all_items:
                all_paid = all(li.status == 'handled_paid' for li in all_items)
                any_in_progress = any(li.status in ('handled_paid', 'handled_not_paid', 'paid_not_handled') for li in all_items)
                any_pending = any(li.status == 'not_handled' for li in all_items)
                
                # Update job card status
                old_status = job.status
                if all_paid:
                    job.status = 'completed'
                    job.completed_at = timezone.now()
                    job.save(update_fields=['status', 'completed_at'])
                    if old_status != 'completed':
                        StaffActivityLog.objects.create(
                            job_card=job, staff=request.user,
                            action='Job card auto-completed (all items paid and handled)'
                        )
                        _auto_log_time(job, request.user, 'Job completed — all items handled and paid', Decimal('0.25'))
                elif any_in_progress:
                    if job.status == 'open':
                        job.status = 'in_progress'
                        job.save(update_fields=['status'])
                        StaffActivityLog.objects.create(
                            job_card=job, staff=request.user,
                            action='Job card moved to in progress'
                        )
            
            # Update invoice status
            if hasattr(job, 'invoice'):
                inv = job.invoice
                all_items = list(job.line_items.all())
                all_paid = all(li.status == 'handled_paid' for li in all_items)
                any_handled = any(li.status in ('handled_paid','handled_not_paid','paid_not_handled') for li in all_items)
                if all_paid:
                    inv.amount_paid = inv.grand_total
                    inv.status = 'paid'
                    inv.save()
                    from django.db.models import Sum
                    from billing.models import Invoice
                    client = job.client
                    out = Invoice.objects.filter(client=client).exclude(status='paid').aggregate(s=Sum('grand_total'))['s'] or 0
                    paid_sum = Invoice.objects.filter(client=client).aggregate(s=Sum('amount_paid'))['s'] or 0
                    client.total_outstanding = max(0, out - paid_sum)
                    client.save(update_fields=['total_outstanding'])
                elif any_handled and inv.status == 'draft':
                    inv.status = 'sent'
                    inv.save(update_fields=['status'])
    return redirect('services:detail', pk=item.job_card.pk)

@login_required
def update_jobcard_status(request, pk):
    """Job card status is now auto-updated based on line items. Manual updates disabled."""
    job = get_object_or_404(JobCard, pk=pk)
    messages.info(request, 'Job card status is automatically updated based on line item progress. Update individual line items to change job status.')
    return redirect('services:detail', pk=pk)

@login_required
def service_list(request):
    ctx = _service_catalogue_context(request)
    services = ctx.get('services')
    page_obj = paginate_queryset(request, services.order_by('category', 'name'), per_page=50)
    ctx['services'] = page_obj
    ctx['page_obj'] = page_obj
    return render(request, 'services/service_list.html', ctx)


@login_required
def service_create(request):
    """Admin/Manager only: add a new service type."""
    if not _can_manage_services(request.user):
        messages.error(request, 'Only managers and admins can add services.')
        return redirect('services:catalogue')
    if request.method == 'POST':
        form = ServiceTypeForm(request.POST)
        if form.is_valid():
            service = form.save(commit=False)
            service.is_active = True
            service.save()
            messages.success(request, f'Service "{service.name}" added.')
            return redirect('services:catalogue')
        messages.error(request, 'Please fix the service details below.')
        return render(request, 'services/service_list.html', _service_catalogue_context(
            request, service_form=form, open_add_modal=True
        ))
    return redirect('services:catalogue')


@login_required
def service_toggle(request, pk):
    """Admin/Manager only: activate or deactivate a service."""
    if not _can_manage_services(request.user):
        messages.error(request, 'Permission denied.')
        return redirect('services:catalogue')
    svc = get_object_or_404(ServiceType, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action', 'toggle')
        if action in ('delete', 'remove'):
            has_usage = svc.jobcardlineitem_set.exists() or svc.clientservicesubscription_set.exists()
            if has_usage:
                if svc.is_active:
                    svc.is_active = False
                    svc.save(update_fields=['is_active'])
                    messages.success(request, f'Service "{svc.name}" removed from the active catalogue.')
                else:
                    messages.info(request, f'Service "{svc.name}" is already inactive.')
            else:
                name = svc.name
                svc.delete()
                messages.success(request, f'Service "{name}" deleted.')
        elif action == 'restore':
            svc.is_active = True
            svc.save(update_fields=['is_active'])
            messages.success(request, f'Service "{svc.name}" restored.')
    return redirect('services:catalogue')


@login_required
def log_time(request, pk):
    job = get_object_or_404(JobCard, pk=pk)
    if request.method == 'POST':
        hours = request.POST.get('hours', '').strip()
        description = request.POST.get('description', '').strip()
        entry_date = request.POST.get('entry_date') or timezone.now().date()
        if hours and description:
            from decimal import Decimal, InvalidOperation
            try:
                TimeEntry.objects.create(
                    job_card=job,
                    staff=request.user,
                    description=description,
                    hours=Decimal(hours),
                    entry_date=entry_date,
                )
                messages.success(request, f'{hours}h logged on {job.job_number}.')
            except (InvalidOperation, ValueError):
                messages.error(request, 'Invalid hours value.')
        else:
            messages.error(request, 'Hours and description are required.')
    return redirect('services:detail', pk=pk)
