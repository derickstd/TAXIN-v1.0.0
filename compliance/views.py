from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import ComplianceObligation, ComplianceDeadline
from billing.models import Invoice, Payment
from services.models import JobCard, JobCardLineItem


@login_required
def deadline_list(request):
    today = timezone.now().date()
    seven_days = today + timezone.timedelta(days=7)
    ComplianceDeadline.objects.filter(status='upcoming', due_date__lt=today).update(status='overdue')
    upcoming = ComplianceDeadline.objects.filter(
        status='upcoming', due_date__lte=seven_days
    ).select_related('obligation__client', 'obligation__service_type').order_by('due_date')
    all_deadlines = ComplianceDeadline.objects.select_related(
        'obligation__client', 'obligation__service_type', 'filed_by', 'invoice'
    ).order_by('due_date')[:100]
    return render(request, 'compliance/deadline_list.html', {
        'upcoming': upcoming, 'all_deadlines': all_deadlines, 'today': today,
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
            invoice.status = 'paid'
            invoice.amount_paid = invoice.grand_total
            invoice.payment_method = 'mixed'
            invoice.save(update_fields=['status', 'amount_paid', 'payment_method'])
            _create_payment_if_needed(invoice, request.user)
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
            invoice.status = 'sent'
            invoice.save(update_fields=['status'])
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
            invoice.status = 'paid'
            invoice.amount_paid = invoice.grand_total
            invoice.payment_method = 'mixed'
            invoice.save(update_fields=['status', 'amount_paid', 'payment_method'])
            _create_payment_if_needed(invoice, request.user)
        deadline.job_card = job_card
        deadline.invoice = invoice
        messages.success(request, f'Payment recorded for {service_type.name} {deadline.period_label} (pending filing).')

    elif action == 'none':
        deadline.status = 'none'
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
            invoice.status = 'draft'
            invoice.amount_paid = 0
            invoice.save(update_fields=['status', 'amount_paid'])
            invoice.payments.all().delete()
        messages.info(request, f'{service_type.name} for {deadline.period_label} reset to no action.')

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
    if not invoice.payments.exists():
        Payment.objects.create(
            invoice=invoice,
            amount=invoice.grand_total,
            method='mixed',
            received_by=user,
            notes='Payment recorded via compliance action',
        )
