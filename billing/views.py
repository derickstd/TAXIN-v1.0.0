from io import BytesIO
from xml.sax.saxutils import escape
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import F, Sum, Q, Count
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
from uuid import UUID, uuid4
from .models import (
    BranchDailySummary, BranchDailyTransaction, Invoice, OtherIncome, Payment,
    PaymentSubmission,
)
from .forms import InvoiceForm, PaymentReceiptFilterForm
from clients.models import Client
from services.models import JobCard, JobCardLineItem, ServiceType, StaffActivityLog
from services.forms import service_category_choices
from core.utils import paginate_queryset
from core.duplicate_detection import check_duplicate_transaction
from core.branch_access import accessible_branches, get_entry_branch, scope_queryset


def _claim_payment_submission(request, action):
    raw_token = request.POST.get('payment_submission_token', '').strip()
    if not raw_token:
        return None, None
    try:
        token = UUID(raw_token)
    except ValueError:
        return None, 'invalid'

    submission, created = PaymentSubmission.objects.get_or_create(
        token=token,
        defaults={'user': request.user, 'action': action},
    )
    if created:
        return submission, None
    if submission.user_id != request.user.pk or submission.action != action:
        return None, 'invalid'
    return submission, 'duplicate'


def _release_payment_submission(submission):
    if submission:
        submission.delete()


def _complete_payment_submission(submission, message, redirect_url):
    if not submission:
        return
    submission.message = message
    submission.redirect_url = redirect_url
    submission.save(update_fields=['message', 'redirect_url'])


def _duplicate_payment_response(request, submission, fallback_url, is_ajax=False):
    message = submission.message or 'This payment submission has already been processed.'
    message = f'{message} No duplicate was created.'
    if is_ajax:
        return JsonResponse({
            'success': True,
            'duplicate': True,
            'message': message,
        })
    messages.info(request, message)
    return redirect(submission.redirect_url or fallback_url)


@login_required
def invoice_list(request):
    invoices = scope_queryset(
        request.user, Invoice.objects.select_related('client', 'job_card'),
    )
    status = request.GET.get('status', '')
    q = request.GET.get('q', '')
    if status:
        invoices = invoices.filter(status=status)
    if q:
        invoices = invoices.filter(
            Q(invoice_number__icontains=q) | Q(client__full_name__icontains=q))
    today = timezone.now().date()
    invoices.filter(status__in=['sent', 'partially_paid'], due_date__lt=today).update(status='overdue')
    agg = invoices.aggregate(total_invoiced=Sum('grand_total'), total_paid=Sum('amount_paid'))
    total_invoiced = agg['total_invoiced'] or 0
    total_paid = agg['total_paid'] or 0
    totals = {'total_invoiced': total_invoiced, 'total_paid': total_paid,
              'outstanding': total_invoiced - total_paid}
    page_obj = paginate_queryset(request, invoices.order_by('-date_issued'), per_page=25)
    return render(request, 'billing/invoice_list.html', {
        'invoices': page_obj, 'page_obj': page_obj, 'status': status, 'q': q,
        'status_choices': Invoice.STATUS, 'totals': totals,
    })


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(scope_queryset(request.user, Invoice.objects.all()), pk=pk)
    payments = invoice.payments.order_by('payment_date', 'pk')
    # Build running balance per payment (allow negative balance when overpaid)
    running = invoice.grand_total
    payments_with_balance = []
    for pmt in payments:
        running -= pmt.amount
        payments_with_balance.append((pmt, running))
    from django.conf import settings
    firm_address = getattr(settings, 'FIRM_ADDRESS', 'Kampala, Uganda')
    firm_phone   = getattr(settings, 'FIRM_PHONE',   '+256 785 230 670')
    firm_email   = getattr(settings, 'FIRM_EMAIL',   'info@Taxin.com')
    return render(request, 'billing/invoice_detail.html', {
        'invoice': invoice,
        'payments': payments,
        'payments_with_balance': payments_with_balance,
        'payment_submission_token': uuid4(),
        'firm_address': firm_address,
        'firm_phone': firm_phone,
        'firm_email': firm_email,
    })


@login_required
def payment_receipts_report(request):
    filter_form = PaymentReceiptFilterForm(request.GET, user=request.user)
    payments = scope_queryset(
        request.user,
        Payment.objects.select_related(
            'client', 'invoice', 'service_type', 'branch', 'received_by',
        ),
    )

    if filter_form.is_valid():
        filters = filter_form.cleaned_data
        if filters['search']:
            search = filters['search'].strip()
            search_query = (
                Q(reference__icontains=search)
                | Q(client__full_name__icontains=search)
                | Q(client__client_id__icontains=search)
                | Q(invoice__invoice_number__icontains=search)
                | Q(service_type__name__icontains=search)
            )
            parts = search.upper().split('-')
            if (
                len(parts) == 3 and parts[0] == 'RCT'
                and len(parts[1]) == 4 and parts[1].isdigit()
                and parts[2].isdigit()
                and len(parts[2]) <= 18
            ):
                search_query |= Q(
                    pk=int(parts[2]),
                    payment_date__year=int(parts[1]),
                )
            payments = payments.filter(search_query)
        if filters['date_from']:
            payments = payments.filter(payment_date__gte=filters['date_from'])
        if filters['date_to']:
            payments = payments.filter(payment_date__lte=filters['date_to'])
        if filters['method']:
            payments = payments.filter(method=filters['method'])
        if filters['branch']:
            payments = payments.filter(branch=filters['branch'])
    else:
        payments = Payment.objects.none()

    totals = payments.aggregate(
        record_count=Count('pk'),
        amount=Sum('amount'),
    )
    page_obj = paginate_queryset(
        request, payments.order_by('-payment_date', '-pk'), per_page=30,
    )
    return render(request, 'billing/payments_report.html', {
        'filter_form': filter_form,
        'payments': page_obj,
        'page_obj': page_obj,
        'record_count': totals['record_count'],
        'total_amount': totals['amount'] or Decimal('0.00'),
        'can_delete_records': (
            request.user.is_superuser
            or request.user.role in ('admin', 'ceo')
        ),
    })


def _payment_receipt_branch_and_company(payment):
    branch = payment.branch
    if branch is None and payment.invoice_id:
        branch = payment.invoice.branch
    if branch is None and payment.client_id:
        branch = payment.client.branch

    received_by = payment.received_by
    company = branch.company if branch else None
    if company is None and received_by and received_by.company_id:
        company = received_by.company
    if branch is None and company:
        branch = company.default_branch
    if branch:
        company = branch.company
    return branch, company


def _payment_receipt_pdf(payment, branch, company):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=48 * mm,
        bottomMargin=20 * mm,
        title=f'Payment Receipt {payment.receipt_number}',
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ReceiptTitle',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=17,
        leading=22,
        textColor=colors.HexColor('#0e7490'),
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    label_style = ParagraphStyle(
        'ReceiptLabel',
        parent=styles['BodyText'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#164e63'),
    )
    value_style = ParagraphStyle(
        'ReceiptValue',
        parent=styles['BodyText'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#1f2937'),
    )

    def paragraph(value, style):
        text = escape(str(value if value not in (None, '') else '—'))
        return Paragraph(text.replace('\n', '<br/>'), style)

    customer_name = (
        payment.client.get_display_name()
        if payment.client_id else 'Unassigned'
    )
    received_by_name = '—'
    if payment.received_by_id:
        received_by_name = (
            payment.received_by.get_full_name()
            or payment.received_by.username
        )
    details = [
        ('Receipt number', payment.receipt_number),
        ('Payment date', payment.payment_date.strftime('%d %b %Y')),
        ('Received from', customer_name),
        ('Invoice', payment.invoice.invoice_number if payment.invoice_id else '—'),
        ('Service', payment.service_type.name if payment.service_type_id else '—'),
        ('Payment method', payment.get_payment_method_display()),
        ('Reference', payment.reference or '—'),
        ('Received by', received_by_name),
        ('Amount paid', f'UGX {payment.amount:,.2f}'),
    ]
    if branch:
        details.insert(2, ('Branch', branch.name))
        if branch.address:
            details.insert(3, ('Branch address', branch.address))
        if branch.phone:
            details.insert(4, ('Branch phone', branch.phone))
    if company:
        if company.registration_number:
            details.append(('Registration number', company.registration_number))
        if company.tin:
            details.append(('Company TIN', company.tin))
        if company.email:
            details.append(('Company email', company.email))

    rows = [
        [paragraph(label, label_style), paragraph(value, value_style)]
        for label, value in details
    ]
    receipt_table = Table(rows, colWidths=[42 * mm, 128 * mm], hAlign='LEFT')
    receipt_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0fdff')),
        ('GRID', (0, 0), (-1, -1), .5, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('BACKGROUND', (0, len(rows) - 1), (-1, len(rows) - 1), colors.HexColor('#e0f9fc')),
        ('LINEABOVE', (0, len(rows) - 1), (-1, len(rows) - 1), 1, colors.HexColor('#0e7490')),
    ]))
    story = [
        Paragraph('PAYMENT RECEIPT', title_style),
        receipt_table,
    ]
    if payment.notes:
        story.extend([
            Spacer(1, 10 * mm),
            Paragraph('Notes', label_style),
            Paragraph(
                escape(payment.notes).replace('\n', '<br/>'),
                value_style,
            ),
        ])
    story.extend([
        Spacer(1, 12 * mm),
        Paragraph(
            'This is a computer-generated receipt.',
            ParagraphStyle(
                'ReceiptFooter',
                parent=value_style,
                alignment=TA_CENTER,
                textColor=colors.HexColor('#64748b'),
            ),
        ),
    ])

    def draw_branding(pdf_canvas, doc):
        page_width, page_height = A4
        x = doc.leftMargin
        top = page_height - 15 * mm
        if branch and branch.logo:
            with branch.logo.open('rb') as logo_file:
                image = ImageReader(logo_file)
                image_width, image_height = image.getSize()
                scale = min((26 * mm) / image_width, (23 * mm) / image_height)
                pdf_canvas.drawImage(
                    image,
                    x,
                    top - 23 * mm,
                    width=image_width * scale,
                    height=image_height * scale,
                    mask='auto',
                )
            x += 32 * mm

        pdf_canvas.saveState()
        pdf_canvas.setFillColor(colors.HexColor('#164e63'))
        pdf_canvas.setFont('Helvetica-Bold', 11)
        pdf_canvas.drawString(x, top - 5 * mm, (company.name if company else 'Taxin')[:55])
        if branch:
            pdf_canvas.setFont('Helvetica', 9)
            pdf_canvas.drawString(x, top - 11 * mm, branch.name[:70])
            phone = branch.phone or (company.phone if company else '')
            if phone:
                pdf_canvas.setFont('Helvetica', 8)
                pdf_canvas.drawString(x, top - 17 * mm, phone[:75])
        pdf_canvas.setStrokeColor(colors.HexColor('#0e7490'))
        pdf_canvas.setLineWidth(1)
        pdf_canvas.line(
            doc.leftMargin, page_height - 41 * mm,
            page_width - doc.rightMargin, page_height - 41 * mm,
        )
        pdf_canvas.setFont('Helvetica', 8)
        pdf_canvas.setFillColor(colors.HexColor('#64748b'))
        pdf_canvas.drawRightString(
            page_width - doc.rightMargin,
            12 * mm,
            f'{payment.receipt_number} | Taxin',
        )
        pdf_canvas.restoreState()

    document.build(story, onFirstPage=draw_branding, onLaterPages=draw_branding)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="{payment.receipt_number}.pdf"'
    )
    return response


@login_required
def payment_receipt(request, pk):
    payments = scope_queryset(
        request.user,
        Payment.objects.select_related(
            'branch__company',
            'invoice__branch__company',
            'client__branch__company',
            'service_type',
            'received_by__company__default_branch__company',
        ),
    )
    payment = get_object_or_404(payments, pk=pk)
    branch, company = _payment_receipt_branch_and_company(payment)
    if request.GET.get('format') == 'pdf':
        return _payment_receipt_pdf(payment, branch, company)
    return render(request, 'billing/payment_receipt.html', {
        'payment': payment,
        'branch': branch,
        'company': company,
        'can_delete_records': (
            request.user.is_superuser
            or request.user.role in ('admin', 'ceo')
        ),
    })


@login_required
@require_POST
def payment_delete(request, pk):
    if not (request.user.is_superuser or request.user.role in ('admin', 'ceo')):
        messages.error(request, 'Only CEOs and admins can delete payments.')
        return redirect('billing:payments_report')

    payments = scope_queryset(
        request.user,
        Payment.objects.select_related('invoice', 'client'),
    )
    payment = get_object_or_404(payments, pk=pk)
    receipt_number = payment.receipt_number
    payment._audit_actor = request.user
    payment.delete()
    messages.success(
        request,
        f'Payment {receipt_number} deleted and related balances updated.',
    )
    return redirect('billing:payments_report')


@login_required
def invoice_create(request):
    """Unified view to create Tax Invoice, Pro Forma Invoice, or Quotation."""
    branch = get_entry_branch(request.user)
    if branch and branch.external_reporting:
        messages.info(request, 'Use Branch Daily Entries for this branch; it reports from an external accounting system.')
        return redirect('documents:branch_daily_summaries')
    if request.method == 'POST':
        client_id = request.POST.get('client')
        client = get_object_or_404(scope_queryset(request.user, Client.objects.all()), pk=client_id)
        document_type = request.POST.get('document_type', 'invoice')
        amount_str = request.POST.get('amount', '0')
        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, TypeError):
            messages.error(request, 'Invalid amount.')
            return redirect('billing:create')
        desc = request.POST.get('description', 'Professional Services')
        
        # Handle due date based on document type
        due_date_str = request.POST.get('due_date', '')
        if due_date_str:
            try:
                from datetime import date
                due_date = date.fromisoformat(due_date_str)
            except ValueError:
                due_date = timezone.now().date() + timezone.timedelta(days=14)
        else:
            # Default: 14 days for invoice, 30 days for proforma/quotation
            if document_type == 'invoice':
                due_date = timezone.now().date() + timezone.timedelta(days=14)
            else:
                due_date = timezone.now().date() + timezone.timedelta(days=30)
        
        # Handle valid_until for proforma/quotation
        valid_until_str = request.POST.get('valid_until', '')
        valid_until = None
        if valid_until_str:
            try:
                from datetime import date
                valid_until = date.fromisoformat(valid_until_str)
            except ValueError:
                pass
        
        # Set status based on document type
        if document_type == 'invoice':
            status = 'sent'
        else:
            status = 'draft'
        
        # Check for similar invoices recently created for same client/amount
        similar_invoices = scope_queryset(request.user, Invoice.objects.filter(
            client=client,
            document_type=document_type,
            created_at__gte=timezone.now() - timezone.timedelta(days=14),
        )).order_by('-created_at')
        allow_create = True
        for s in similar_invoices:
            # compare amounts within small tolerance
            try:
                if abs(float(s.grand_total) - float(amount)) <= max(1.0, float(amount) * 0.01):
                    allow_create = False
                    break
            except Exception:
                continue

        if not allow_create and request.POST.get('force_create') != '1':
            return render(request, 'billing/invoice_create.html', {
                'clients': scope_queryset(
                    request.user,
                    Client.objects.filter(status__in=['active', 'dormant', 'suspended']),
                ).order_by('full_name'),
                'client': client,
                'document_type': document_type,
                'amount': amount,
                'description': desc,
                'due_date': due_date_str,
                'valid_until': valid_until_str,
                'show_duplicate_modal': True,
                'similar_invoices': similar_invoices[:5],
                'orig_post': request.POST,
            })

        inv = Invoice.objects.create(
            client=client, document_type=document_type,
            branch=client.branch or get_entry_branch(request.user),
            due_date=due_date, valid_until=valid_until,
            subtotal=amount, vat_total=0, grand_total=amount,
            status=status, notes=desc, created_by=request.user)
        
        doc_label = inv.get_doc_label()
        messages.success(request, f'{doc_label} {inv.invoice_number} created.')
        return redirect('billing:detail', pk=inv.pk)
    
    clients = scope_queryset(
        request.user,
        Client.objects.filter(status__in=['active', 'dormant', 'suspended']),
    ).order_by('full_name')
    return render(request, 'billing/invoice_create.html', {'clients': clients})


@login_required
def invoice_edit(request, pk):
    invoice = get_object_or_404(scope_queryset(request.user, Invoice.objects.all()), pk=pk)
    if invoice.branch_id and invoice.branch.external_reporting:
        messages.info(request, 'External-system branch transactions are reported through daily summaries.')
        return redirect('documents:branch_daily_summaries')
    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice, user=request.user)
        if form.is_valid():
            inv = form.save(commit=False)
            if invoice.document_type != 'invoice' and inv.document_type == 'invoice':
                inv.invoice_number = Invoice.next_invoice_number('invoice', exclude_pk=invoice.pk)
                inv.status = 'sent'
            inv.save()
            messages.success(request, f'Invoice {inv.invoice_number} updated.')
            return redirect('billing:detail', pk=inv.pk)
    else:
        form = InvoiceForm(instance=invoice, user=request.user)
    return render(request, 'billing/invoice_form.html', {
        'form': form, 'invoice': invoice, 'title': f'Edit {invoice.invoice_number}'
    })


@login_required
def invoice_delete(request, pk):
    invoice = get_object_or_404(scope_queryset(request.user, Invoice.objects.all()), pk=pk)
    if invoice.branch_id and invoice.branch.external_reporting:
        messages.info(request, 'External-system branch transactions are reported through daily summaries.')
        return redirect('documents:branch_daily_summaries')
    if invoice.payments.exists():
        messages.error(request, 'Cannot delete an invoice with recorded payments.')
        return redirect('billing:detail', pk=pk)
    if request.method == 'POST':
        invoice_number = invoice.invoice_number
        invoice._audit_actor = request.user
        invoice.delete()
        messages.success(request, f'Invoice {invoice_number} deleted.')
        return redirect('billing:list')
    return render(request, 'billing/invoice_confirm_delete.html', {'invoice': invoice})


@login_required
@transaction.atomic
def record_payment(request, pk):
    invoice = get_object_or_404(scope_queryset(request.user, Invoice.objects.all()), pk=pk)
    if request.method == 'POST':
        submission = None
        payment_branch = (
            invoice.branch or invoice.client.branch or get_entry_branch(request.user)
        )
        if payment_branch and payment_branch.external_reporting:
            messages.error(request, 'Use the branch daily summary instead of individual payments for this branch.')
            return redirect('documents:branch_daily_summaries')
        try:
            from decimal import Decimal, InvalidOperation
            from core.email_utils import send_payment_receipt

            amount = Decimal(str(request.POST.get('amount', 0)))
            if amount <= 0:
                messages.error(request, 'Payment amount must be greater than zero.')
                return redirect('billing:detail', pk=pk)

            method = request.POST.get('method', 'cash')
            reference = request.POST.get('reference', '')
            payment_date_raw = request.POST.get('payment_date', '').strip()
            try:
                payment_date = date.fromisoformat(payment_date_raw) if payment_date_raw else timezone.localdate()
            except ValueError:
                messages.error(request, 'Enter a valid payment date.')
                return redirect('billing:detail', pk=pk)
            submission, replay = _claim_payment_submission(request, 'invoice')
            if replay == 'invalid':
                messages.error(request, 'Refresh the payment form before submitting again.')
                return redirect('billing:detail', pk=pk)
            if replay == 'duplicate':
                return _duplicate_payment_response(
                    request, submission, reverse('billing:detail', args=[pk]),
                )
            with transaction.atomic():
                invoice = scope_queryset(
                    request.user, Invoice.objects.all(),
                ).select_for_update().get(pk=pk)
                invoice.refresh_from_db(fields=['grand_total', 'amount_paid'])
                remaining = amount
                unapplied_amount = Decimal('0')
                created_payments = []

            # Apply the payment to the current invoice first, then to earlier unpaid
            # invoices for the same client if the amount exceeds the current invoice balance.
                earlier_invoices = list(
                scope_queryset(
                    request.user, Invoice.objects.all(),
                ).select_for_update().filter(client=invoice.client)
                .exclude(pk=invoice.pk)
                .exclude(status__in=['paid', 'written_off'])
                .filter(
                    Q(date_issued__lt=invoice.date_issued)
                    | Q(date_issued=invoice.date_issued, pk__lt=invoice.pk)
                )
                .order_by('date_issued', 'pk')
                )
                candidate_invoices = earlier_invoices + [invoice]
                for inv in candidate_invoices:
                    if remaining <= 0:
                        break
                    inv.refresh_from_db(fields=['grand_total', 'amount_paid'])
                    balance = inv.grand_total - inv.amount_paid
                    if balance <= 0:
                        continue
                    to_apply = min(balance, remaining)
                    if to_apply <= 0:
                        continue
                    payment = Payment.objects.create(
                        invoice=inv, branch=inv.branch or payment_branch,
                        amount=to_apply, method=method,
                        payment_date=payment_date,
                        reference=reference, received_by=request.user)
                    created_payments.append(payment)
                    remaining -= to_apply

                if remaining > 0:
                    unapplied_amount = remaining
                    credit = Payment.objects.create(
                        client=invoice.client, branch=invoice.branch or payment_branch,
                        amount=remaining, method=method,
                        payment_date=payment_date,
                        reference=reference, received_by=request.user)
                    created_payments.append(credit)
                    remaining = Decimal('0')

            if not created_payments:
                _release_payment_submission(submission)
                messages.info(request, 'No outstanding balance could be allocated.')
                return redirect('billing:detail', pk=pk)

            invoice.refresh_from_db()
            client = invoice.client

            # Send payment receipt email for the first payment created
            if client.email and created_payments:
                send_payment_receipt(created_payments[0])

            current_balance = invoice.grand_total - invoice.amount_paid
            if unapplied_amount:
                confirmation = (
                    f'Payment of UGX {amount:,.0f} recorded. '
                    f'Excess UGX {unapplied_amount:,.0f} is unapplied client credit.'
                )
            elif current_balance <= 0:
                if len(created_payments) > 1:
                    confirmation = f'Payment of UGX {amount:,.0f} recorded and applied to this invoice and earlier outstanding invoices.'
                else:
                    confirmation = f'Payment of UGX {amount:,.0f} recorded. Invoice fully paid.'
            else:
                confirmation = f'Payment of UGX {amount:,.0f} recorded. Remaining balance: UGX {current_balance:,.0f}.'
            _complete_payment_submission(
                submission, confirmation, reverse('billing:detail', args=[pk]),
            )
            messages.success(request, confirmation)
        except (InvalidOperation, TypeError) as e:
            _release_payment_submission(submission)
            messages.error(request, f'Invalid payment amount: {e}')
    return redirect('billing:detail', pk=pk)


@login_required
@transaction.atomic
def record_client_payment(request):
    """Accept a lump-sum payment for a client and allocate it to their oldest
    unpaid invoices (using the invoice amounts as the recorded agreed prices).
    Records any amount beyond outstanding invoices as unapplied client credit.
    """
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('billing:list')
    branch = get_entry_branch(request.user)
    if branch and branch.external_reporting:
        messages.error(request, 'Use the branch daily summary instead of individual payments for this branch.')
        return redirect('documents:branch_daily_summaries')

    client_id = request.POST.get('client')
    amount_raw = request.POST.get('amount', '0')
    method = request.POST.get('method', 'cash')
    reference = request.POST.get('reference', '')
    selected_invoice_ids = request.POST.getlist('invoice_ids')
    try:
        amount = Decimal(str(amount_raw))
    except (InvalidOperation, TypeError):
        messages.error(request, 'Invalid payment amount.')
        return redirect('billing:list')

    client = get_object_or_404(scope_queryset(request.user, Client.objects.all()), pk=client_id)
    if client.branch_id and client.branch.external_reporting:
        messages.error(request, 'Use the Daily Transaction Ledger for this external-system branch.')
        return redirect('clients:detail', pk=client.pk)
    payment_branch = client.branch or get_entry_branch(request.user)
    payment_date_raw = request.POST.get('payment_date')
    try:
        payment_date = timezone.datetime.fromisoformat(payment_date_raw).date() if payment_date_raw else timezone.now().date()
    except ValueError:
        messages.error(request, 'Invalid payment date.')
        return redirect('clients:detail', pk=client.pk)

    if amount <= 0:
        messages.error(request, 'Payment amount must be greater than zero.')
        return redirect('billing:detail', pk=client.invoices.first().pk if client.invoices.exists() else 'billing:list')

    submission, replay = _claim_payment_submission(request, 'client')
    if replay == 'invalid':
        messages.error(request, 'Refresh the payment form before submitting again.')
        return redirect('clients:detail', pk=client.pk)
    if replay == 'duplicate':
        return _duplicate_payment_response(
            request, submission, reverse('clients:detail', args=[client.pk]),
        )

    # Fetch unpaid invoices oldest-first and allocate the lump sum across all
    # outstanding invoices for the client so earlier periods are cleared first.
    unpaid = scope_queryset(request.user, Invoice.objects.filter(client=client)).exclude(
        status__in=['paid', 'written_off'],
    )
    if selected_invoice_ids:
        unpaid = unpaid.filter(pk__in=selected_invoice_ids)
    unpaid = unpaid.order_by('date_issued', 'pk')

    with transaction.atomic():
        unpaid = unpaid.select_for_update()
        remaining = amount
        allocated_count = 0
        for inv in unpaid:
            if remaining <= 0:
                break
            inv.refresh_from_db(fields=['grand_total', 'amount_paid'])
            balance = inv.grand_total - inv.amount_paid
            if balance <= 0:
                continue
            to_apply = min(balance, remaining)
            if to_apply <= 0:
                continue
            Payment.objects.create(
                invoice=inv,
                branch=inv.branch or payment_branch,
                amount=to_apply,
                method=method,
                payment_date=payment_date,
                reference=reference,
                received_by=request.user
            )
            remaining -= to_apply
            allocated_count += 1

        if remaining > 0:
            if selected_invoice_ids and allocated_count == 0:
                _release_payment_submission(submission)
                messages.error(request, 'The selected invoices have no outstanding balance.')
                return redirect('clients:detail', pk=client.pk)
            Payment.objects.create(
                client=client,
                branch=payment_branch,
                amount=remaining,
                method=method,
                payment_date=payment_date,
                reference=reference,
                received_by=request.user,
            )

    if allocated_count and remaining:
        confirmation = (
            f'Allocated payment to {allocated_count} invoice(s). '
            f'Excess UGX {remaining:,.0f} is unapplied client credit.'
        )
    elif allocated_count:
        confirmation = f'Allocated payment to {allocated_count} invoice(s).'
    elif remaining:
        confirmation = f'Payment of UGX {remaining:,.0f} recorded as unapplied client credit.'
    else:
        _release_payment_submission(submission)
        messages.info(request, 'No unpaid invoices found for this client.')
        return redirect('clients:detail', pk=client.pk)

    _complete_payment_submission(
        submission, confirmation, reverse('clients:detail', args=[client.pk]),
    )
    messages.success(request, confirmation)
    # Optionally send receipt for first payment created (signals already updated invoices)
    return redirect('clients:detail', pk=client.pk)


def _is_walkin_client_name(name):
    normalized = ''.join(character for character in name.casefold() if character.isalnum())
    return normalized.startswith(('anon', 'walkin'))


def _get_walkin_customer(user):
    branch = get_entry_branch(user)
    client, _ = Client.objects.get_or_create(
        full_name__iexact='Walk-in Customers',
        branch=branch,
        defaults={
            'full_name': 'Walk-in Customers',
            'phone_primary': 'N/A',
            'district': 'Kampala',
            'created_by': user,
            'branch': branch,
            'notes': 'Shared account for anonymous walk-in customer payments.',
        },
    )
    return client


def _create_quick_payment_job_card(client, service_type, amount, payment_date, branch, user, notes, *, paid):
    period_month = payment_date.month if service_type.deadline_type != 'none' else None
    period_year = payment_date.year if service_type.deadline_type != 'none' else None
    line_total = amount
    vat_amount = Decimal('0')
    if service_type.vat_applicable:
        line_total = (amount / Decimal('1.18')).quantize(Decimal('0.01'))
        vat_amount = amount - line_total

    job = JobCard.objects.create(
        client=client,
        branch=branch,
        period_month=period_month,
        period_year=period_year,
        notes=notes,
        created_by=user,
    )
    JobCardLineItem.objects.create(
        job_card=job,
        service_type=service_type,
        default_price=service_type.default_price,
        negotiated_price=line_total,
        vat_amount=vat_amount,
        status='handled_paid' if paid else 'handled_not_paid',
        period_label=payment_date.strftime('%B %Y') if period_month else '',
        notes=notes[:300],
    )
    StaffActivityLog.objects.create(
        job_card=job,
        staff=user,
        action='Job card created from quick payment',
    )
    return job


@login_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def quick_payment(request):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    submission = None

    def payment_error(message):
        _release_payment_submission(submission)
        if is_ajax:
            return JsonResponse({'error': message}, status=400)
        messages.error(request, message)
        return redirect('billing:quick_payment')

    if request.method == 'POST':
        amount_raw = request.POST.get('amount', '').strip()
        try:
            amount = Decimal(amount_raw)
        except (InvalidOperation, TypeError):
            return payment_error('Enter a valid payment amount.')
        if amount <= 0:
            return payment_error('Payment amount must be greater than zero.')
        if amount > Decimal('9999999999999.99'):
            return payment_error('Payment amount exceeds the supported limit.')
        try:
            rounded_amount = amount.quantize(Decimal('0.01'))
        except InvalidOperation:
            return payment_error('Enter a valid payment amount.')
        if amount != rounded_amount:
            return payment_error('Payment amount can have at most two decimal places.')
        amount = rounded_amount

        method = request.POST.get('method', 'cash')
        quick_payment_methods = Payment.METHOD + [('credit', 'Credit')]
        if method not in dict(quick_payment_methods):
            return payment_error('Select a valid payment method.')

        payment_date_raw = request.POST.get('payment_date', '').strip()
        try:
            payment_date = date.fromisoformat(payment_date_raw) if payment_date_raw else timezone.localdate()
        except ValueError:
            return payment_error('Enter a valid payment date.')

        reference = request.POST.get('reference', '').strip()
        if len(reference) > 100:
            return payment_error('Payment reference must be 100 characters or fewer.')

        client_id = request.POST.get('client', '').strip()
        is_registered_client = False
        try:
            if client_id:
                client = scope_queryset(request.user, Client.objects.all()).get(pk=client_id)
                if _is_walkin_client_name(client.full_name):
                    client = _get_walkin_customer(request.user)
                else:
                    is_registered_client = True
            else:
                client = _get_walkin_customer(request.user)
        except (Client.DoesNotExist, ValueError, TypeError):
            return payment_error('Select a valid customer.')

        payment_branch = client.branch or get_entry_branch(request.user)
        is_external_branch = bool(
            payment_branch and payment_branch.external_reporting
        )
        if is_external_branch and payment_date > timezone.localdate():
            return payment_error('An external-branch payment cannot be dated in the future.')

        service_type = None
        service_id = request.POST.get('service_type', '').strip()
        is_capital_injection = service_id == 'capital_injection'
        if service_id and not is_capital_injection:
            service_type = scope_queryset(
                request.user,
                ServiceType.objects.filter(is_active=True),
                branch_path='branches',
            ).distinct().filter(pk=service_id).first()
            if not service_type:
                return payment_error('Select a valid service for this workspace.')

        if (
            service_type and payment_branch
            and not service_type.branches.filter(pk=payment_branch.pk).exists()
        ):
            return payment_error('The selected service is not available to this client’s branch.')

        notes = request.POST.get('notes', '').strip()
        submission, replay = _claim_payment_submission(request, 'quick')
        if replay == 'invalid':
            return payment_error('Refresh the payment form before submitting again.')
        if replay == 'duplicate':
            return _duplicate_payment_response(
                request,
                submission,
                reverse('billing:quick_payment'),
                is_ajax=is_ajax,
            )

        if method == 'credit':
            if is_capital_injection:
                return payment_error('Capital injections must use a cash or bank payment method.')
            if not is_registered_client:
                return payment_error('Credit sales require a registered customer.')
            if not service_type:
                return payment_error('Select a service to create a customer credit.')
            if payment_date > timezone.localdate():
                return payment_error('A credit sale cannot be dated in the future.')

            invoice_notes = f'Credit sale: {service_type.name}'
            if reference:
                invoice_notes += f'\nReference: {reference}'
            if notes:
                invoice_notes += f'\n{notes}'
            with transaction.atomic():
                job = None
                subtotal = amount
                vat_total = Decimal('0')
                if not is_external_branch:
                    job = _create_quick_payment_job_card(
                        client, service_type, amount, payment_date, payment_branch,
                        request.user, notes, paid=False,
                    )
                    vat_total = sum(
                        item.vat_amount for item in job.line_items.all()
                    )
                    subtotal = job.total_fee - vat_total
                credit_invoice = Invoice.objects.create(
                    client=client,
                    branch=payment_branch,
                    service_type=service_type,
                    job_card=job,
                    is_credit_sale=True,
                    due_date=payment_date + timedelta(days=14),
                    subtotal=subtotal,
                    vat_total=vat_total,
                    grand_total=amount,
                    status='sent',
                    notes=invoice_notes,
                    created_by=request.user,
                )
                Invoice.objects.filter(pk=credit_invoice.pk).update(
                    date_issued=payment_date,
                )
            engagement_note = f'on job card {job.job_number} and ' if job else ''
            confirmation = (
                f'UGX {amount:,.0f} recorded as credit for '
                f'{client.get_display_name()} {engagement_note}'
                f'on invoice {credit_invoice.invoice_number}. '
                f'Due {credit_invoice.due_date:%d %b %Y}. No cash payment was recorded.'
            )
            _complete_payment_submission(
                submission,
                confirmation,
                reverse('clients:detail', args=[client.pk]),
            )
            messages.success(request, confirmation)
            if is_ajax:
                return JsonResponse({'success': True, 'message': confirmation})
            return redirect('clients:detail', pk=client.pk)

        if is_capital_injection:
            if payment_date > timezone.localdate():
                return payment_error('A capital injection cannot be dated in the future.')
            description_parts = ['Capital injection']
            if is_registered_client:
                description_parts.append(f'Contributor: {client.get_display_name()}')
            if notes:
                description_parts.append(notes)
            description = ' — '.join(description_parts)[:255]
            try:
                with transaction.atomic():
                    if is_external_branch:
                        summary = BranchDailySummary.objects.select_for_update().filter(
                            branch=payment_branch,
                            business_date=payment_date,
                        ).first()
                        if summary and summary.reviewed_at:
                            return payment_error(
                                'This branch day has been reviewed and locked. '
                                'Record the capital injection on an open business date.'
                            )
                        account_for_method = {
                            'cash': 'cash',
                            'mobile_money': 'mobile_money',
                            'bank_transfer': 'bank_transfer',
                        }
                        BranchDailyTransaction.objects.create(
                            branch=payment_branch,
                            business_date=payment_date,
                            direction='inflow',
                            category='capital_injection',
                            description=description,
                            account=account_for_method[method],
                            amount=amount,
                            reference=reference,
                            entered_by=request.user,
                        )
                    else:
                        OtherIncome.objects.create(
                            source_name='Capital injection',
                            category='capital_injection',
                            amount=amount,
                            income_date=payment_date,
                            collection_method=method,
                            reference=reference,
                            description=description,
                            recorded_by=request.user,
                            branch=payment_branch,
                        )
            except IntegrityError:
                return payment_error(
                    'This reference has already been recorded for the branch and date.'
                )
            confirmation = (
                f'UGX {amount:,.0f} capital injection recorded for '
                f'{payment_branch.name if payment_branch else "the company"}.'
            )
            if is_external_branch:
                confirmation += ' Added to Branch Daily Entries.'
            _complete_payment_submission(
                submission,
                confirmation,
                reverse('billing:quick_payment'),
            )
            messages.success(request, confirmation)
            if is_ajax:
                return JsonResponse({'success': True, 'message': confirmation})
            return redirect('billing:quick_payment')

        allocated_count = 0
        remaining = amount
        unpaid_invoices = scope_queryset(
            request.user, Invoice.objects.filter(client=client),
        ).exclude(status__in=['paid', 'written_off']).order_by('date_issued', 'pk')
        if is_external_branch:
            unpaid_invoices = unpaid_invoices.filter(branch=payment_branch)
        try:
            with transaction.atomic():
                if is_external_branch:
                    summary = BranchDailySummary.objects.select_for_update().filter(
                        branch=payment_branch,
                        business_date=payment_date,
                    ).first()
                    if summary and summary.reviewed_at:
                        return payment_error(
                            'This branch day has been reviewed and locked. '
                            'Record the payment on an open business date.'
                        )

                if service_type and not is_external_branch:
                    job = _create_quick_payment_job_card(
                        client, service_type, amount, payment_date, payment_branch,
                        request.user, notes, paid=True,
                    )
                    vat_total = sum(
                        item.vat_amount for item in job.line_items.all()
                    )
                    invoice = Invoice.objects.create(
                        client=client,
                        branch=payment_branch,
                        service_type=service_type,
                        job_card=job,
                        due_date=payment_date + timedelta(days=14),
                        subtotal=job.total_fee - vat_total,
                        vat_total=vat_total,
                        grand_total=amount,
                        status='sent',
                        payment_method=method,
                        notes=notes,
                        created_by=request.user,
                    )
                    Invoice.objects.filter(pk=invoice.pk).update(
                        date_issued=payment_date,
                    )
                    Payment.objects.create(
                        invoice=invoice,
                        client=client,
                        service_type=service_type,
                        amount=amount,
                        payment_date=payment_date,
                        method=method,
                        reference=reference,
                        notes=notes,
                        received_by=request.user,
                        branch=payment_branch,
                    )
                    allocated_count = 1
                    remaining = Decimal('0')
                else:
                    for invoice in unpaid_invoices.select_for_update():
                        if remaining <= 0:
                            break
                        invoice.refresh_from_db(fields=['grand_total', 'amount_paid'])
                        balance = invoice.grand_total - invoice.amount_paid
                        if balance <= 0:
                            continue
                        applied_amount = min(balance, remaining)
                        Payment.objects.create(
                            invoice=invoice,
                            client=client,
                            service_type=service_type,
                            amount=applied_amount,
                            payment_date=payment_date,
                            method=method,
                            reference=reference,
                            notes=notes,
                            received_by=request.user,
                            branch=invoice.branch or payment_branch,
                        )
                        remaining -= applied_amount
                        allocated_count += 1

                    if remaining > 0:
                        Payment.objects.create(
                            client=client,
                            service_type=service_type,
                            amount=remaining,
                            payment_date=payment_date,
                            method=method,
                            reference=reference,
                            notes=notes,
                            received_by=request.user,
                            branch=payment_branch,
                        )

                if is_external_branch:
                    account_for_method = {
                        'cash': 'cash',
                        'mobile_money': 'mobile_money',
                        'bank_transfer': 'bank_transfer',
                    }
                    description = f'Customer payment — {client.get_display_name()}'
                    if service_type:
                        description += f' — {service_type.name}'
                    BranchDailyTransaction.objects.create(
                        branch=payment_branch,
                        business_date=payment_date,
                        direction='inflow',
                        category='service_receipt',
                        description=description[:255],
                        account=account_for_method[method],
                        amount=amount,
                        reference=reference,
                        entered_by=request.user,
                    )
        except IntegrityError:
            return payment_error(
                'This reference has already been recorded for the branch and date.'
            )

        if allocated_count and service_type and not is_external_branch:
            confirmation = (
                f'UGX {amount:,.0f} recorded for {client.get_display_name()} and '
                f'applied to a new handled and paid engagement for {service_type.name}.'
            )
        elif allocated_count:
            confirmation = (
                f'UGX {amount:,.0f} recorded for {client.get_display_name()} and '
                f'allocated to {allocated_count} oldest outstanding invoice(s).'
            )
            if remaining:
                confirmation += f' Excess UGX {remaining:,.0f} is recorded as unapplied client credit.'
        else:
            confirmation = (
                f'UGX {amount:,.0f} recorded for {client.get_display_name()} as an '
                'unapplied payment on account.'
            )
        if is_external_branch:
            confirmation += ' Added to Branch Daily Entries.'
        _complete_payment_submission(
            submission,
            confirmation,
            reverse('clients:detail', args=[client.pk]),
        )
        messages.success(request, confirmation)
        if is_ajax:
            return JsonResponse({'success': True, 'message': confirmation})
        return redirect('clients:detail', pk=client.pk)

    clients = scope_queryset(
        request.user, Client.objects.only('pk', 'client_id', 'full_name'),
    ).order_by('full_name')
    services = scope_queryset(
        request.user,
        ServiceType.objects.filter(is_active=True).prefetch_related('branches'),
        branch_path='branches',
    ).distinct().order_by('name')
    context = {
        'clients': clients,
        'payment_submission_token': uuid4(),
        'services': services,
        'payment_methods': Payment.METHOD + [('credit', 'Credit')],
        'client_types': Client.CLIENT_TYPE,
        'service_categories': service_category_choices(),
        'service_branches': accessible_branches(request.user),
        'can_manage_services': request.user.is_superuser or request.user.is_manager_or_admin(),
    }
    if request.GET.get('popover') == '1':
        return render(request, 'billing/partials/quick_payment_popover.html', context)
    return render(request, 'billing/quick_payment.html', context)


@login_required
def aging_report(request):
    invoices = scope_queryset(
        request.user,
        Invoice.objects.exclude(status__in=['paid', 'written_off']).select_related('client'),
    )
    buckets = {'Current': [], '1–30 days': [], '31–60 days': [], '61–90 days': [], '90+ days': []}
    for inv in invoices:
        buckets[inv.aging_bucket()].append(inv)
    bucket_totals = {k: sum(float(i.balance_due) for i in v) for k, v in buckets.items()}
    return render(request, 'billing/aging_report.html', {'buckets': buckets, 'bucket_totals': bucket_totals})


@login_required
def bad_debt_report(request):
    from services.models import JobCardLineItem, mark_overdue_handled_tasks

    mark_overdue_handled_tasks()
    items = (scope_queryset(
             request.user, JobCardLineItem.objects.filter(status='bad_debt'),
             branch_path='job_card__branch',
             )
             .select_related('job_card__client', 'job_card__invoice', 'service_type')
             .order_by('job_card__client__full_name', 'job_card__created_at'))
    total = sum(item.line_total() for item in items)
    return render(request, 'billing/bad_debt_report.html', {
        'items': items,
        'total': total,
        'as_of': timezone.now().date(),
    })


@login_required
def send_invoice_whatsapp(request, pk):
    invoice = get_object_or_404(scope_queryset(request.user, Invoice.objects.all()), pk=pk)
    from notifications.services import send_whatsapp_message, send_email_notification
    from core.email_utils import send_invoice_email
    
    # Prepare WhatsApp message
    msg = (f"Dear {invoice.client.get_display_name()},\n\n"
           f"Invoice {invoice.invoice_number} from Taxin.\n"
           f"Total: UGX {invoice.grand_total:,.0f}\n"
           f"Balance Due: UGX {invoice.balance_due:,.0f}\n"
           f"Due Date: {invoice.due_date}\n\n"
           f"Pay to: +256785230670 (Mobile Money)\n"
           f"Ref: {invoice.invoice_number}\n\nThank you.")
    
    sent_count = 0
    
    # Send WhatsApp
    wa = invoice.client.get_whatsapp_number()
    if wa:
        result = send_whatsapp_message(wa, msg, client=invoice.client,
                                       msg_type='invoice_delivery', triggered_by=request.user)
        if result:
            sent_count += 1
    
    # Send HTML Email
    if invoice.client.email:
        email_result = send_invoice_email(invoice)
        if email_result:
            sent_count += 1
    
    invoice.sent_via_whatsapp = True
    invoice.sent_at = timezone.now()
    invoice.save(update_fields=['sent_via_whatsapp', 'sent_at'])
    
    if sent_count == 0:
        messages.warning(request, 'Client has no WhatsApp or Email on file.')
    elif sent_count == 1:
        messages.success(request, 'Invoice sent via WhatsApp or Email.')
    else:
        messages.success(request, f'Invoice sent via WhatsApp and Email to {invoice.client.get_display_name()}.')
    
    return redirect('billing:detail', pk=pk)



@login_required
def convert_to_invoice(request, pk):
    """Convert a quotation/proforma to a tax invoice."""
    inv = get_object_or_404(scope_queryset(request.user, Invoice.objects.all()), pk=pk)
    if request.method == 'POST':
        if inv.document_type != 'invoice':
            inv.document_type = 'invoice'
            inv.status = 'sent'
            inv.invoice_number = Invoice.next_invoice_number('invoice', exclude_pk=inv.pk)
            inv.save()
            messages.success(request, f'Converted to Invoice {inv.invoice_number}.')
        else:
            messages.info(request, 'Already a tax invoice.')
    return redirect('billing:detail', pk=pk)


@login_required
def refresh_outstanding_balances(request):
    """Manually refresh all client outstanding balances"""
    if request.method == 'POST':
        from billing.signals import update_client_outstanding
        
        clients = scope_queryset(request.user, Client.objects.all())
        updated = 0
        
        for client in clients:
            old_balance = client.total_outstanding
            update_client_outstanding(client)
            client.refresh_from_db()
            if old_balance != client.total_outstanding:
                updated += 1
        
        messages.success(request, f'✅ Refreshed outstanding balances for all clients. {updated} updated.')
    
    return redirect('clients:list')


@login_required
def refresh_outstanding_balances_json(request):
    """Refresh client outstanding balances and return them to the browser."""
    from billing.signals import update_client_outstanding

    clients = scope_queryset(request.user, Client.objects.all())
    result = {}
    for client in clients:
        update_client_outstanding(client)
        result[str(client.pk)] = str(client.total_outstanding)

    return JsonResponse({'clients': result})


@login_required
def other_income_list(request):
    """List all other income entries with filtering by category and date."""
    incomes = scope_queryset(
        request.user, OtherIncome.objects.select_related('recorded_by'),
    )
    category = request.GET.get('category', '')
    q = request.GET.get('q', '')
    
    if category:
        incomes = incomes.filter(category=category)
    if q:
        incomes = incomes.filter(
            Q(source_name__icontains=q) | Q(reference__icontains=q) | Q(description__icontains=q)
        )
    
    # Aggregates
    totals = incomes.aggregate(
        total_income=Sum('amount'),
        count=Count('id')
    )
    total_income = totals['total_income'] or 0
    count = totals['count'] or 0
    avg_income = float(total_income) / count if count > 0 else 0
    
    page_obj = paginate_queryset(request, incomes.order_by('-income_date'), per_page=20)
    
    return render(request, 'billing/otherincome_list.html', {
        'incomes': page_obj,
        'page_obj': page_obj,
        'category': category,
        'q': q,
        'category_choices': OtherIncome.CATEGORY,
        'total_income': total_income,
        'count': count,
        'avg_income': avg_income,
    })


@login_required
def other_income_create(request):
    """Create a new other income entry."""
    branch = get_entry_branch(request.user)
    if branch and branch.external_reporting:
        messages.error(request, 'Record external-branch totals in Branch Daily Entries instead of individual income transactions.')
        return redirect('documents:branch_daily_summaries')
    if request.method == 'POST':
        try:
            source_name = request.POST.get('source_name', '').strip()
            category = request.POST.get('category', 'other')
            amount = Decimal(request.POST.get('amount', 0))
            income_date = request.POST.get('income_date')
            collection_method = request.POST.get('collection_method', 'bank_transfer')
            reference = request.POST.get('reference', '').strip()
            description = request.POST.get('description', '').strip()
            
            if not source_name:
                messages.error(request, 'Source name is required.')
                return redirect('billing:otherincome_create')
            
            if amount <= 0:
                messages.error(request, 'Amount must be greater than zero.')
                return redirect('billing:otherincome_create')
            
            income = OtherIncome.objects.create(
                source_name=source_name,
                category=category,
                amount=amount,
                income_date=income_date or timezone.now().date(),
                collection_method=collection_method,
                reference=reference,
                description=description,
                recorded_by=request.user,
                branch=branch,
            )
            
            messages.success(request, f'✓ Other income "{source_name}" recorded successfully.')
            return redirect('billing:otherincome_list')
        
        except (ValueError, InvalidOperation) as e:
            messages.error(request, f'Invalid input: {str(e)}')
            return redirect('billing:otherincome_create')
    
    return render(request, 'billing/otherincome_form.html', {
        'category_choices': OtherIncome.CATEGORY,
        'method_choices': OtherIncome.METHOD,
    })


@login_required
def other_income_detail(request, pk):
    """View details of a single other income entry."""
    income = get_object_or_404(scope_queryset(request.user, OtherIncome.objects.all()), pk=pk)
    return render(request, 'billing/otherincome_detail.html', {'income': income})


@login_required
def other_income_delete(request, pk):
    """Delete an other income entry."""
    income = get_object_or_404(scope_queryset(request.user, OtherIncome.objects.all()), pk=pk)
    if request.method == 'POST':
        source_name = income.source_name
        income.delete()
        messages.success(request, f'✓ Deleted other income "{source_name}".')
        return redirect('billing:otherincome_list')
    
    return render(request, 'billing/otherincome_confirm_delete.html', {'income': income})

