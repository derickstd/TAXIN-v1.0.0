from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal
from .models import JobCard, JobCardLineItem, ServiceType, StaffActivityLog
from .forms import JobCardForm, LineItemFormSet, ServiceTypeForm
import calendar as cal


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
    jobs = JobCard.objects.select_related('client','assigned_to').prefetch_related('line_items').all()
    status = request.GET.get('status','')
    q = request.GET.get('q','')
    if status: jobs = jobs.filter(status=status)
    if q: jobs = jobs.filter(Q(job_number__icontains=q)|Q(client__full_name__icontains=q))
    kanban = {s: [j for j in jobs if j.status == s] for s,_ in JobCard.STATUS}
    return render(request, 'services/jobcard_list.html', {
        'jobs': jobs, 'kanban': kanban, 'status': status, 'q': q,
        'status_choices': JobCard.STATUS, 'today': timezone.now().date(),
    })

@login_required
def jobcard_detail(request, pk):
    job = get_object_or_404(JobCard, pk=pk)
    logs = job.activity_logs.select_related('staff').all()
    return render(request, 'services/jobcard_detail.html', {'job': job, 'logs': logs})

@login_required
def jobcard_create(request):
    today = timezone.now()
    years = list(range(today.year - 1, today.year + 3))
    from core.models import User
    default_officer = User.objects.filter(role='tax_officer', is_active=True).first()

    if request.method == 'POST':
        form = JobCardForm(request.POST)
        formset = LineItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            job = form.save(commit=False)
            job.created_by = request.user
            job.save()
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
            _auto_create_invoice(job, request.user)
            StaffActivityLog.objects.create(job_card=job, staff=request.user, action='Job card created')
            messages.success(request, f'Job card {job.job_number} created. Invoice auto-generated.')
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
        return
    subtotal = sum(li.negotiated_price for li in job.line_items.all())
    vat_total = sum(li.vat_amount for li in job.line_items.all())
    due = job.due_date or (timezone.now().date() + timezone.timedelta(days=14))
    Invoice.objects.create(
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
            job = item.job_card
            if hasattr(job, 'invoice'):
                inv = job.invoice
                all_items = list(job.line_items.all())
                all_paid = all(li.status == 'handled_paid' for li in all_items)
                any_handled = any(li.status in ('handled_paid','handled_not_paid') for li in all_items)
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
    job = get_object_or_404(JobCard, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status == 'completed':
            if hasattr(job, 'invoice') and job.invoice.status not in ('paid','written_off'):
                messages.error(request, '❌ Cannot complete job — invoice must be fully paid first.')
                return redirect('services:detail', pk=pk)
            job.completed_at = timezone.now()
        job.status = new_status
        job.save()
        StaffActivityLog.objects.create(job_card=job, staff=request.user,
            action=f'Status changed to {job.get_status_display()}')
        messages.success(request, f'Status updated to {job.get_status_display()}.')
    return redirect('services:detail', pk=pk)

@login_required
def service_list(request):
    return render(request, 'services/service_list.html', _service_catalogue_context(request))


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
