from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from .models import JobCard, JobCardLineItem, ServiceType, StaffActivityLog, TimeEntry
from .forms import JobCardForm, LineItemFormSet, ServiceTypeForm
import calendar as cal
from core.utils import paginate_queryset
from clients.models import Client
from core.models import User


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


def _parse_period_label(period_label):
    if not period_label:
        return None, None
    parts = period_label.strip().split()
    if len(parts) < 2:
        return None, None
    year = parts[-1]
    month_name = ' '.join(parts[:-1])
    try:
        month = next(i for i in range(1, 13) if cal.month_name[i].lower() == month_name.lower())
        return month, int(year)
    except (StopIteration, ValueError):
        return None, None


def _get_first_item_period(request):
    def scan_prefix(prefix):
        total = request.POST.get(prefix + 'TOTAL_FORMS')
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = 1
        for idx in range(total):
            period_month = request.POST.get(f'{prefix}{idx}-period_month', '').strip()
            period_year = request.POST.get(f'{prefix}{idx}-period_year', '').strip()
            if period_month and period_year:
                try:
                    return int(period_month), int(period_year)
                except ValueError:
                    pass
            period_label = request.POST.get(f'{prefix}{idx}-period_label', '').strip()
            if period_label:
                parsed = _parse_period_label(period_label)
                if parsed != (None, None):
                    return parsed
        return None, None

    period = scan_prefix('line_items-')
    if period != (None, None):
        return period
    period = scan_prefix('jobcardlineitem_set-')
    if period != (None, None):
        return period

    # Fallback: if a recurring service was selected but no explicit period fields are present,
    # default to the current month/year so duplicate checks still catch same-period jobs.
    svc_id = request.POST.get('line_items-0-service_type') or request.POST.get('jobcardlineitem_set-0-service_type')
    if svc_id:
        svc = ServiceType.objects.filter(pk=svc_id).first()
        if svc and svc.deadline_type != 'none':
            now = timezone.now()
            return now.month, now.year

    return None, None


def _build_period_label(period_month, period_year, existing_label=''):
    if existing_label:
        return existing_label.strip()
    if period_month and period_year:
        try:
            return f"{cal.month_name[int(period_month)]} {period_year}"
        except (ValueError, IndexError):
            pass
    return ''


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


def _get_job_duplicate_state(job):
    from core.duplicate_detection import check_duplicate_transaction

    if not getattr(job, 'period_month', None) or not getattr(job, 'period_year', None):
        return False, []

    duplicate_candidates = []
    candidate_services = [
        item.service_type for item in job.line_items.select_related('service_type').all()
        if item.service_type
    ]

    for service in candidate_services:
        duplicate_candidates.extend(check_duplicate_transaction(
            client=job.client,
            service_type=service,
            job_card=job,
            period_year=job.period_year,
            period_month=job.period_month,
            within_days=365,
        ))

    return bool(duplicate_candidates), duplicate_candidates


def _get_job_task_counts(job):
    paid_statuses = ['handled_paid', 'paid_not_handled']
    unpaid_statuses = ['handled_not_paid', 'not_handled']
    paid_tasks = job.line_items.filter(status__in=paid_statuses).count()
    unpaid_tasks = job.line_items.filter(status__in=unpaid_statuses).count()
    return paid_tasks, unpaid_tasks


@login_required
def jobcard_list(request):
    all_jobs_qs = JobCard.objects.select_related('client','assigned_to').prefetch_related('line_items').all()
    status = request.GET.get('status','')
    q = request.GET.get('q','')
    jobs_qs = all_jobs_qs
    if status: jobs_qs = jobs_qs.filter(status=status)
    if q:
        jobs_qs = jobs_qs.filter(Q(job_number__icontains=q) | Q(client__full_name__icontains=q))

    all_jobs = list(all_jobs_qs)
    for job in all_jobs:
        job.is_duplicate_transaction, job.duplicate_candidates = _get_job_duplicate_state(job)

    kanban_cols = [(s, label, [job for job in all_jobs if job.status == s]) for s, label in JobCard.STATUS]
    page_obj = paginate_queryset(request, jobs_qs.order_by('-created_at'), per_page=25)
    duplicate_statuses = {}
    for job in page_obj.object_list:
        job.is_duplicate_transaction, job.duplicate_candidates = _get_job_duplicate_state(job)
        duplicate_statuses[job.pk] = job.is_duplicate_transaction

    duplicate_count = sum(1 for is_dup in duplicate_statuses.values() if is_dup)

    return render(request, 'services/jobcard_list.html', {
        'jobs': page_obj, 'page_obj': page_obj, 'kanban_cols': kanban_cols, 'status': status, 'q': q,
        'status_choices': JobCard.STATUS, 'today': timezone.now().date(),
        'duplicate_count': duplicate_count,
        'duplicate_statuses': duplicate_statuses,
    })

@login_required
def jobcard_detail(request, pk):
    job = get_object_or_404(JobCard, pk=pk)
    logs = job.activity_logs.select_related('staff').all()
    time_entries = job.time_entries.select_related('staff').all()
    total_hours = sum(t.hours for t in time_entries)

    is_duplicate_transaction, duplicate_candidates = _get_job_duplicate_state(job)
    paid_task_count, unpaid_task_count = _get_job_task_counts(job)

    return render(request, 'services/jobcard_detail.html', {
        'job': job, 'logs': logs,
        'time_entries': time_entries, 'total_hours': total_hours,
        'today': timezone.now().date(),
        'is_duplicate_transaction': is_duplicate_transaction,
        'duplicate_candidates': duplicate_candidates,
        'paid_task_count': paid_task_count,
        'unpaid_task_count': unpaid_task_count,
    })

@login_required
def jobcard_create(request):
    today = timezone.now()
    years = list(range(today.year - 1, today.year + 3))
    from core.models import User
    default_officer = User.objects.filter(role='tax_officer', is_active=True).first()

    if request.method == 'POST':
        form = JobCardForm(request.POST)
        formset = LineItemFormSet(request.POST, prefix='line_items')
        intake_pk = request.POST.get('walkin_intake_pk')
        from_walkin = bool(intake_pk) or bool(request.POST.get('new_job_reg'))

        # Before creating, check for similar existing transactions to avoid duplicates
        from core.duplicate_detection import check_duplicate_transaction
        period_month, period_year = _get_first_item_period(request)
        svc_id = None
        total = request.POST.get('line_items-TOTAL_FORMS')
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = 1
        for idx in range(total):
            candidate = request.POST.get(f'line_items-{idx}-service_type')
            if candidate:
                svc_id = candidate
                break
        if not svc_id:
            total = request.POST.get('jobcardlineitem_set-TOTAL_FORMS')
            try:
                total = int(total)
            except (TypeError, ValueError):
                total = 1
            for idx in range(total):
                candidate = request.POST.get(f'jobcardlineitem_set-{idx}-service_type')
                if candidate:
                    svc_id = candidate
                    break
        svc = ServiceType.objects.filter(pk=svc_id).first() if svc_id else None
        client_obj = None
        client_pk = request.POST.get('client')
        if client_pk:
            client_obj = Client.objects.filter(pk=client_pk).first()
        similar = check_duplicate_transaction(
            client=client_obj,
            service_type=svc,
            period_year=period_year,
            period_month=period_month,
            within_days=14,
        )
        if similar:
            # allow force-create via POST param
            if request.POST.get('force_create') == '1':
                pass
            else:
                return render(request, 'services/jobcard_form.html', {
                    'form': form,
                    'formset': formset,
                    'title': 'New Job Card',
                    'years': years,
                    'current_year': today.year,
                    'default_officer': default_officer,
                    'duplicate_warning': True,
                    'duplicate_similar': similar,
                    'duplicate_candidates': similar,
                    'duplicate_orig_post': request.POST,
                })

        if form.is_valid() and (formset.is_valid() or from_walkin):
            job = form.save(commit=False)
            if period_month and period_year:
                job.period_month = period_month
                job.period_year = period_year
            job.created_by = request.user
            job.save()

            if from_walkin:
                # Build line item directly from POST — ignore formset validation entirely
                svc_id = request.POST.get('line_items-0-service_type') or request.POST.get('jobcardlineitem_set-0-service_type')
                price_raw = request.POST.get('line_items-0-negotiated_price', '0') or request.POST.get('jobcardlineitem_set-0-negotiated_price', '0')
                default_raw = request.POST.get('line_items-0-default_price', '0') or request.POST.get('jobcardlineitem_set-0-default_price', '0')
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
                    custom_description='' if svc else request.POST.get('line_items-0-custom_description', 'Walk-in visit'),
                    default_price=default_price or (svc.default_price if svc else Decimal('0')),
                    negotiated_price=price,
                    vat_amount=vat,
                    status='not_handled',
                    period_label=_build_period_label(period_month, period_year, request.POST.get('line_items-0-period_label', '')),
                    notes=request.POST.get('line_items-0-notes', ''),
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
            StaffActivityLog.objects.create(job_card=job, staff=request.user, action='Job card created')
            _auto_log_time(job, request.user, 'Job card created', Decimal('0.25'))
            if intake_pk:
                from clients.models import WalkInIntake
                WalkInIntake.objects.filter(pk=intake_pk).update(outcome='job_created')
            messages.success(request, f'Job card {job.job_number} created. No invoice is generated until a task is marked handled.')
            return redirect('services:detail', pk=job.pk)
        else:
            messages.error(request, 'Please fix the errors below.')
    else:
        client_id = request.GET.get('client')
        initial = {}
        if client_id:
            initial['client'] = client_id
        form = JobCardForm(initial=initial)
        formset = LineItemFormSet(prefix='line_items')

    return render(request, 'services/jobcard_form.html', {
        'form': form, 'formset': formset, 'title': 'New Job Card',
        'years': years, 'current_year': today.year,
        'default_officer': default_officer,
    })


def _parse_decimal(value, default='0'):
    try:
        return Decimal(value) if value not in (None, '') else Decimal(default)
    except Exception:
        return Decimal(default)


def _get_quick_create_post_value(request, *names):
    for name in names:
        value = request.POST.get(name)
        if value not in (None, ''):
            return value
    return ''


def _get_quick_create_period(request):
    month = _get_quick_create_post_value(request,
        'period_month',
        'jobcardlineitem_set-0-period_month',
        'line_items-0-period_month'
    )
    year = _get_quick_create_post_value(request,
        'period_year',
        'jobcardlineitem_set-0-period_year',
        'line_items-0-period_year'
    )
    if month and year:
        try:
            return int(month), int(year)
        except ValueError:
            pass
    label = _get_quick_create_post_value(request,
        'period_label',
        'jobcardlineitem_set-0-period_label',
        'line_items-0-period_label'
    )
    if label:
        parsed = _parse_period_label(label)
        if parsed != (None, None):
            return parsed
    return None, None


@login_required
def jobcard_quick_create(request):
    if request.method != 'POST':
        return redirect('services:list')

    from core.duplicate_detection import check_duplicate_transaction
    from billing.models import Invoice, Payment

    client_pk = request.POST.get('client')
    service_pk = _get_quick_create_post_value(request,
        'service_type',
        'jobcardlineitem_set-0-service_type',
        'line_items-0-service_type'
    )
    client = Client.objects.filter(pk=client_pk).first() if client_pk else None
    service = ServiceType.objects.filter(pk=service_pk).first() if service_pk else None
    period_month, period_year = _get_quick_create_period(request)

    if not client or not service:
        messages.error(request, 'Client and service selection are required to create a job card.')
        return redirect(request.META.get('HTTP_REFERER', reverse('clients:list')))

    if not period_month or not period_year:
        if service.deadline_type != 'none':
            now = timezone.now()
            period_month, period_year = now.month, now.year

    similar = check_duplicate_transaction(
        client=client,
        service_type=service,
        period_year=period_year,
        period_month=period_month,
        within_days=14,
    )
    if similar and request.POST.get('force_create') != '1':
        messages.warning(request, 'A similar transaction already exists for this client and service period.')
        request.session['duplicate_matches'] = [
            {'type': item.get('type'), 'description': item.get('description'), 'date': item.get('date') or item.get('due_date')}
            for item in similar
        ]
        return redirect(request.META.get('HTTP_REFERER', reverse('clients:detail', args=[client.pk])))

    assigned_to_id = _get_quick_create_post_value(request,
        'assigned_to',
        'jobcardlineitem_set-0-assigned_to',
        'line_items-0-assigned_to'
    )
    assigned_to = User.objects.filter(pk=assigned_to_id).first() if assigned_to_id else None

    job = JobCard(
        client=client,
        assigned_to=assigned_to,
        priority=request.POST.get('priority', 'normal'),
        notes=request.POST.get('notes', '').strip(),
        created_by=request.user,
    )
    if period_month and period_year:
        job.period_month = period_month
        job.period_year = period_year
    due_date = request.POST.get('due_date')
    if due_date:
        try:
            job.due_date = timezone.datetime.fromisoformat(due_date).date()
        except Exception:
            pass
    job.save()

    negotiated_price = _parse_decimal(_get_quick_create_post_value(request,
        'negotiated_price',
        'jobcardlineitem_set-0-negotiated_price',
        'line_items-0-negotiated_price'
    ), default='0')
    default_price = _parse_decimal(_get_quick_create_post_value(request,
        'default_price',
        'jobcardlineitem_set-0-default_price',
        'line_items-0-default_price'
    ), default=str(service.default_price if service else 0))
    if negotiated_price <= 0:
        negotiated_price = default_price or (service.default_price if service else Decimal('0'))
    vat_amount = negotiated_price * Decimal('0.18') if service.vat_applicable else Decimal('0')
    JobCardLineItem.objects.create(
        job_card=job,
        service_type=service,
        custom_description=request.POST.get('jobcardlineitem_set-0-custom_description', '') or request.POST.get('line_items-0-custom_description', ''),
        default_price=default_price,
        negotiated_price=negotiated_price,
        vat_amount=vat_amount,
        status='not_handled',
        period_label=_build_period_label(period_month, period_year, _get_quick_create_post_value(request,
            'period_label',
            'jobcardlineitem_set-0-period_label',
            'line_items-0-period_label'
        )),
        notes=request.POST.get('jobcardlineitem_set-0-notes', '') or request.POST.get('line_items-0-notes', ''),
    )

    job.update_total()
    StaffActivityLog.objects.create(job_card=job, staff=request.user, action='Job card created')
    _auto_log_time(job, request.user, 'Job card created', Decimal('0.25'))

    if request.POST.get('create_invoice') == 'yes':
        invoice = _auto_create_invoice(job, request.user)
        if request.POST.get('payment_received') == 'yes' and invoice:
            payment_amount = _parse_decimal(request.POST.get('payment_amount'), default=str(invoice.grand_total))
            if payment_amount <= 0:
                payment_amount = invoice.grand_total
            Payment.objects.create(
                invoice=invoice,
                amount=payment_amount,
                method=request.POST.get('payment_method', 'cash'),
                reference=request.POST.get('payment_reference', ''),
                received_by=request.user,
            )

    intake_pk = request.POST.get('walkin_intake_pk')
    if intake_pk:
        from clients.models import WalkInIntake
        WalkInIntake.objects.filter(pk=intake_pk).update(outcome='job_created')

    messages.success(request, f'Job card {job.job_number} created.')
    return redirect('services:detail', pk=job.pk)


@login_required
def jobcard_edit(request, pk):
    job = get_object_or_404(JobCard, pk=pk)
    today = timezone.now()
    years = list(range(today.year - 1, today.year + 3))
    from core.models import User
    default_officer = User.objects.filter(role='tax_officer', is_active=True).first()

    if request.method == 'POST':
        form = JobCardForm(request.POST, instance=job)
        formset = LineItemFormSet(request.POST, prefix='line_items', instance=job)
        period_month, period_year = _get_first_item_period(request)
        if form.is_valid() and formset.is_valid():
            job = form.save(commit=False)
            if period_month and period_year:
                job.period_month = period_month
                job.period_year = period_year
            job.save()

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
            invoice = getattr(job, 'invoice', None)
            if invoice:
                invoice.subtotal = job.total_fee
                invoice.vat_total = sum((li.vat_amount or Decimal('0')) for li in job.line_items.all())
                invoice.grand_total = invoice.subtotal + invoice.vat_total
                if invoice.amount_paid > invoice.grand_total:
                    invoice.amount_paid = invoice.grand_total
                invoice.save(update_fields=['subtotal', 'vat_total', 'grand_total', 'amount_paid'])
                invoice.update_status()

            messages.success(request, f'Job card {job.job_number} updated successfully.')
            return redirect('services:detail', pk=job.pk)
        messages.error(request, 'Please fix the errors below.')
    else:
        form = JobCardForm(instance=job)
        formset = LineItemFormSet(prefix='line_items', instance=job)

    return render(request, 'services/jobcard_form.html', {
        'form': form, 'formset': formset, 'title': f'Edit {job.job_number}',
        'years': years, 'current_year': today.year,
        'default_officer': default_officer,
        'job': job,
    })


@login_required
def jobcard_delete(request, pk):
    job = get_object_or_404(JobCard, pk=pk)
    if request.method == 'POST':
        if getattr(job, 'invoice', None) and job.invoice.payments.exists():
            messages.error(request, 'Cannot delete a job card when its invoice has recorded payments.')
            return redirect('services:detail', pk=job.pk)
        job_number = job.job_number
        job.delete()
        messages.success(request, f'Job card {job_number} deleted.')
        return redirect('services:list')
    return render(request, 'services/jobcard_confirm_delete.html', {'job': job})


def _auto_create_invoice(job, user):
    from billing.models import Invoice
    if hasattr(job, 'invoice'):
        return None

    # subtotal should be the sum of negotiated prices (net), VAT accounted for separately
    line_total = sum((li.negotiated_price or Decimal('0')) for li in job.line_items.all())
    from expenses.models import Expense
    expense_total = sum((expense.amount or Decimal('0')) for expense in Expense.objects.filter(job_card=job, is_billable=True))
    subtotal = line_total + expense_total
    vat_total = sum((li.vat_amount or Decimal('0')) for li in job.line_items.all())
    due = job.due_date or (timezone.now().date() + timezone.timedelta(days=14))
    grand_total = subtotal + vat_total
    return Invoice.objects.create(
        client=job.client, job_card=job, due_date=due,
        subtotal=subtotal, vat_total=vat_total, grand_total=grand_total,
        status='sent' if subtotal > 0 else 'draft', created_by=user,
    )


@login_required
def ajax_check_duplicate(request):
    """AJAX endpoint: check for duplicate transactions given client/service/period."""
    from core.duplicate_detection import check_duplicate_transaction
    client_pk = request.GET.get('client') or request.POST.get('client')
    svc_id = request.GET.get('service_type') or request.POST.get('service_type')
    period_month = request.GET.get('period_month') or request.POST.get('period_month')
    period_year = request.GET.get('period_year') or request.POST.get('period_year')

    client = None
    if client_pk:
        try:
            client = Client.objects.filter(pk=client_pk).first()
        except Exception:
            client = None

    svc = None
    if svc_id:
        try:
            svc = ServiceType.objects.filter(pk=svc_id).first()
        except Exception:
            svc = None

    try:
        period_year_int = int(period_year) if period_year else None
    except Exception:
        period_year_int = None
    try:
        period_month_int = int(period_month) if period_month else None
    except Exception:
        period_month_int = None

    if (period_month_int is None or period_year_int is None) and svc and svc.deadline_type != 'none':
        now = timezone.now()
        period_month_int = now.month
        period_year_int = now.year

    similar = check_duplicate_transaction(
        client=client,
        service_type=svc,
        period_year=period_year_int,
        period_month=period_month_int,
        within_days=14,
    )

    results = []
    for item in similar:
        itype = item.get('type')
        url = ''
        if itype == 'invoice' and item.get('object'):
            url = f"/billing/{item['object'].pk}/"
        elif itype == 'job_card' and item.get('object'):
            url = f"/services/{item['object'].pk}/"
        elif itype == 'compliance_deadline' and item.get('object'):
            url = f"/compliance/{item['object'].pk}/"
        results.append({'type': itype, 'description': item.get('description'), 'url': url, 'date': item.get('date') or item.get('due_date') or item.get('created_at')})

    return JsonResponse({'matches': results})

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
            
            handled_state = new_status in {'handled_paid', 'handled_not_paid'}
            if handled_state and not hasattr(job, 'invoice'):
                _auto_create_invoice(job, request.user)

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
