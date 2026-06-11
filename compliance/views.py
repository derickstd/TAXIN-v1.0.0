from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import ComplianceObligation, ComplianceDeadline
from billing.models import Invoice, Payment
from services.models import JobCard, JobCardLineItem
from credentials.models import ClientCredential


@login_required
def deadline_list(request):
    from core.utils import paginate_queryset
    
    today = timezone.now().date()
    seven_days = today + timezone.timedelta(days=7)
    ComplianceDeadline.objects.filter(status='upcoming', due_date__lt=today).update(status='overdue')
    upcoming = ComplianceDeadline.objects.filter(
        status='upcoming', due_date__lte=seven_days
    ).select_related('obligation__client', 'obligation__service_type').order_by('due_date')
    all_deadlines = ComplianceDeadline.objects.select_related(
        'obligation__client', 'obligation__service_type', 'filed_by', 'invoice'
    ).order_by('due_date')

    credentials = ClientCredential.objects.select_related('client', 'last_accessed_by').order_by('client__full_name')
    q = request.GET.get('q', '')
    if q:
        from django.db.models import Q
        credentials = credentials.filter(
            Q(client__full_name__icontains=q) | Q(label__icontains=q)
        )

    page_obj = paginate_queryset(request, all_deadlines, per_page=25)
    
    return render(request, 'compliance/deadline_list.html', {
        'upcoming': upcoming, 'page_obj': page_obj, 'all_deadlines': page_obj, 'today': today,
        'credentials': credentials, 'q': q,
    })


@login_required
def update_status(request, pk, action):
    deadline = get_object_or_404(ComplianceDeadline, pk=pk)
    if request.method != 'POST':
        return redirect('compliance:list')

    service_type = deadline.obligation.service_type

    if action == 'filed_and_paid':
        deadline.status = 'filed_and_paid'
        deadline.filed_date = timezone.now().date()
        deadline.filed_by = request.user
        job_card = _get_or_create_job_card(deadline, request.user)
        if job_card:
            job_card.status = 'completed'
            job_card.completed_at = timezone.now()
            job_card.save(update_fields=['status', 'completed_at'])
            _update_line_item_status(job_card, service_type, 'handled_paid', deadline.period_label)
        invoice = _get_or_create_invoice(deadline, request.user)
        if invoice:
            # Only set status — Payment creation below will set amount_paid via signal
            Invoice.objects.filter(pk=invoice.pk).update(payment_method='mixed')
            _create_payment_if_needed(invoice, request.user)
            # Reload to get signal-updated status
            invoice.refresh_from_db()
        deadline.job_card = job_card
        deadline.invoice = invoice
        messages.success(request, f'{service_type.name} for {deadline.period_label} marked as filed and paid.')

    elif action == 'filed_not_paid':
        deadline.status = 'filed_not_paid'
        deadline.filed_date = timezone.now().date()
        deadline.filed_by = request.user
        job_card = _get_or_create_job_card(deadline, request.user)
        if job_card:
            job_card.status = 'completed'
            job_card.completed_at = timezone.now()
            job_card.save(update_fields=['status', 'completed_at'])
            _update_line_item_status(job_card, service_type, 'handled_not_paid', deadline.period_label)
        invoice = _get_or_create_invoice(deadline, request.user)
        if invoice and invoice.status == 'draft':
            Invoice.objects.filter(pk=invoice.pk).update(status='sent')
        deadline.job_card = job_card
        deadline.invoice = invoice
        messages.success(request, f'{service_type.name} for {deadline.period_label} marked as filed (awaiting payment).')

    elif action == 'paid_not_filed':
        deadline.status = 'paid_not_filed'
        job_card = _get_or_create_job_card(deadline, request.user)
        if job_card:
            job_card.status = 'pending_payment'
            job_card.save(update_fields=['status'])
            _update_line_item_status(job_card, service_type, 'not_handled', deadline.period_label)
        invoice = _get_or_create_invoice(deadline, request.user)
        if invoice:
            Invoice.objects.filter(pk=invoice.pk).update(payment_method='mixed')
            _create_payment_if_needed(invoice, request.user)
            invoice.refresh_from_db()
        deadline.job_card = job_card
        deadline.invoice = invoice
        messages.success(request, f'Payment recorded for {service_type.name} {deadline.period_label} (pending filing).')

    elif action in ('none', 'reset'):
        deadline.status = 'upcoming'
        deadline.filed_date = None
        deadline.filed_by = None
        job_card = _get_job_card_for_deadline(deadline)
        if job_card:
            job_card.status = 'open'
            job_card.completed_at = None
            job_card.save(update_fields=['status', 'completed_at'])
            _update_line_item_status(job_card, service_type, 'not_handled', deadline.period_label)
        invoice = _get_invoice_for_deadline(deadline)
        if invoice:
            # Delete payments first — their deletion signal will recalculate amount_paid
            invoice.payments.all().delete()
            Invoice.objects.filter(pk=invoice.pk).update(status='draft', amount_paid=0)
        messages.info(request, f'{service_type.name} for {deadline.period_label} reset to upcoming.')

    deadline.save()
    return redirect('compliance:list')


def _get_or_create_job_card(deadline, user):
    job_card = _get_job_card_for_deadline(deadline)
    if job_card:
        return job_card
    job_card = JobCard.objects.filter(
        client=deadline.obligation.client,
        period_month=deadline.due_date.month,
        period_year=deadline.due_date.year,
    ).first()
    if not job_card:
        job_card = JobCard.objects.create(
            client=deadline.obligation.client,
            period_month=deadline.due_date.month,
            period_year=deadline.due_date.year,
            assigned_to=user,
            due_date=deadline.due_date,
            is_periodic=True,
            created_by=user,
        )
        JobCardLineItem.objects.create(
            job_card=job_card,
            service_type=deadline.obligation.service_type,
            negotiated_price=deadline.obligation.service_type.default_price,
            vat_amount=0,
            period_label=deadline.period_label,
        )
        job_card.update_total()
    return job_card


def _get_job_card_for_deadline(deadline):
    return deadline.job_card if deadline.job_card_id else None


def _update_line_item_status(job_card, service_type, status, period_label):
    line_item = JobCardLineItem.objects.filter(
        job_card=job_card, service_type=service_type, period_label=period_label,
    ).first()
    if line_item:
        line_item.status = status
        line_item.save(update_fields=['status'])
    else:
        JobCardLineItem.objects.create(
            job_card=job_card, service_type=service_type,
            negotiated_price=service_type.default_price,
            vat_amount=0, status=status, period_label=period_label,
        )
        job_card.update_total()


def _get_or_create_invoice(deadline, user):
    invoice = _get_invoice_for_deadline(deadline)
    if invoice:
        return invoice
    job_card = _get_job_card_for_deadline(deadline)
    if job_card:
        invoice = Invoice.objects.filter(job_card=job_card).first()
        if invoice:
            return invoice
    invoice = Invoice.objects.create(
        client=deadline.obligation.client,
        job_card=job_card,
        due_date=deadline.due_date,
        subtotal=deadline.obligation.service_type.default_price,
        vat_total=0,
        grand_total=deadline.obligation.service_type.default_price,
        created_by=user,
    )
    return invoice


def _get_invoice_for_deadline(deadline):
    return deadline.invoice if deadline.invoice_id else None


def _create_payment_if_needed(invoice, user):
    """Create a payment record only if none exists. The post_save signal handles amount_paid."""
    if not invoice.payments.exists():
        # Reload grand_total fresh from DB before creating payment
        invoice.refresh_from_db(fields=['grand_total', 'amount_paid'])
        Payment.objects.create(
            invoice=invoice,
            amount=invoice.grand_total,
            method='mixed',
            received_by=user,
            notes='Payment recorded via compliance action',
        )


@login_required
def mark_credential_handled(request, pk):
    if request.method != 'POST':
        return redirect('compliance:list')
    credential = get_object_or_404(ClientCredential, pk=pk)
    if 'activate' in request.POST:
        credential.status = 'active'
        credential.save(update_fields=['status'])
        messages.success(request, f'{credential.label} for {credential.client.get_display_name()} activated.')
    else:
        credential.status = 'archived'
        credential.save(update_fields=['status'])
        messages.success(request, f'{credential.label} for {credential.client.get_display_name()} marked as handled.')
    return redirect('compliance:list')
