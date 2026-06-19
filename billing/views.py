from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import F, Sum, Q, Count
from django.http import JsonResponse
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from .models import Invoice, Payment, OtherIncome
from clients.models import Client
from core.utils import paginate_queryset
from core.duplicate_detection import check_duplicate_transaction


@login_required
def invoice_list(request):
    invoices = Invoice.objects.select_related('client', 'job_card').all()
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
    invoice = get_object_or_404(Invoice, pk=pk)
    payments = invoice.payments.order_by('payment_date', 'pk')
    # Build running balance per payment
    running = invoice.grand_total
    payments_with_balance = []
    for pmt in payments:
        running -= pmt.amount
        payments_with_balance.append((pmt, max(running, 0)))
    from django.conf import settings
    firm_address = getattr(settings, 'FIRM_ADDRESS', 'Kampala, Uganda')
    firm_phone   = getattr(settings, 'FIRM_PHONE',   '+256 785 230 670')
    firm_email   = getattr(settings, 'FIRM_EMAIL',   'info@taxman256.com')
    return render(request, 'billing/invoice_detail.html', {
        'invoice': invoice,
        'payments': payments,
        'payments_with_balance': payments_with_balance,
        'firm_address': firm_address,
        'firm_phone': firm_phone,
        'firm_email': firm_email,
    })


@login_required
def invoice_create(request):
    """Unified view to create Tax Invoice, Pro Forma Invoice, or Quotation."""
    if request.method == 'POST':
        client_id = request.POST.get('client')
        client = get_object_or_404(Client, pk=client_id)
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
        similar_invoices = Invoice.objects.filter(
            client=client,
            document_type=document_type,
            created_at__gte=timezone.now().date() - timezone.timedelta(days=14),
        ).order_by('-created_at')
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
            return render(request, 'billing/duplicate_invoice.html', {
                'client': client,
                'document_type': document_type,
                'amount': amount,
                'similar_invoices': similar_invoices[:5],
                'orig_post': request.POST,
            })

        inv = Invoice.objects.create(
            client=client, document_type=document_type,
            due_date=due_date, valid_until=valid_until,
            subtotal=amount, vat_total=0, grand_total=amount,
            status=status, notes=desc, created_by=request.user)
        
        doc_label = inv.get_doc_label()
        messages.success(request, f'{doc_label} {inv.invoice_number} created.')
        return redirect('billing:detail', pk=inv.pk)
    
    clients = Client.objects.filter(status__in=['active', 'dormant', 'suspended']).order_by('full_name')
    return render(request, 'billing/invoice_create.html', {'clients': clients})


@login_required
def record_payment(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        try:
            from decimal import Decimal, InvalidOperation
            from core.email_utils import send_payment_receipt

            amount = Decimal(str(request.POST.get('amount', 0)))
            if amount <= 0:
                messages.error(request, 'Payment amount must be greater than zero.')
                return redirect('billing:detail', pk=pk)

            # Reload fresh from DB before calculating balance — never use stale in-memory value
            invoice.refresh_from_db(fields=['grand_total', 'amount_paid'])
            balance_due = invoice.grand_total - invoice.amount_paid
            if balance_due <= 0:
                messages.info(request, 'This invoice is already fully paid.')
                return redirect('billing:detail', pk=pk)
            # Cap at actual balance — signal will enforce this too but cap here for clean UX
            amount = min(amount, balance_due)

            method = request.POST.get('method', 'cash')
            reference = request.POST.get('reference', '')
            # Creating the Payment triggers the billing signal which recalculates
            # amount_paid, updates invoice status, and refreshes client outstanding
            payment = Payment.objects.create(
                invoice=invoice, amount=amount, method=method,
                reference=reference, received_by=request.user)
            # Reload invoice to get signal-updated values
            invoice.refresh_from_db()
            client = invoice.client

            # Send payment receipt email
            if client.email:
                send_payment_receipt(payment)

            new_balance = invoice.grand_total - invoice.amount_paid
            if new_balance <= 0:
                messages.success(request, f'Payment of UGX {amount:,.0f} recorded. Invoice fully paid.')
            else:
                messages.success(request, f'Payment of UGX {amount:,.0f} recorded. Remaining balance: UGX {new_balance:,.0f}.')
        except (InvalidOperation, TypeError) as e:
            messages.error(request, f'Invalid payment amount: {e}')
    return redirect('billing:detail', pk=pk)


@login_required
def record_client_payment(request):
    """Accept a lump-sum payment for a client and allocate it to their oldest
    unpaid invoices (using the invoice amounts as the recorded agreed prices).
    Creates `Payment` records per invoice until the amount is exhausted.
    """
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('billing:list')

    client_id = request.POST.get('client')
    amount_raw = request.POST.get('amount', '0')
    method = request.POST.get('method', 'cash')
    reference = request.POST.get('reference', '')
    try:
        amount = Decimal(str(amount_raw))
    except (InvalidOperation, TypeError):
        messages.error(request, 'Invalid payment amount.')
        return redirect('billing:list')

    client = get_object_or_404(Client, pk=client_id)
    if amount <= 0:
        messages.error(request, 'Payment amount must be greater than zero.')
        return redirect('billing:detail', pk=client.invoices.first().pk if client.invoices.exists() else 'billing:list')

    # Fetch unpaid invoices oldest-first and allocate
    unpaid = (Invoice.objects.filter(client=client)
                         .exclude(status__in=['paid', 'written_off'])
                         .order_by('date_issued', 'pk'))

    remaining = amount
    created_count = 0
    for inv in unpaid:
        if remaining <= 0:
            break
        inv.refresh_from_db(fields=['grand_total', 'amount_paid'])
        balance = inv.grand_total - inv.amount_paid
        if balance <= 0:
            continue
        to_apply = min(balance, remaining)
        Payment.objects.create(
            invoice=inv,
            amount=to_apply,
            method=method,
            reference=reference,
            received_by=request.user
        )
        remaining -= to_apply
        created_count += 1

    # Update client's last transaction date and outstanding via signals
    if created_count:
        messages.success(request, f'Allocated payment to {created_count} invoice(s). Remaining: UGX {remaining:,.0f}.')
    else:
        messages.info(request, 'No unpaid invoices found for this client.')

    # Optionally send receipt for first payment created (signals already updated invoices)
    return redirect('clients:detail', pk=client.pk)


@login_required
def aging_report(request):
    invoices = Invoice.objects.exclude(status__in=['paid', 'written_off']).select_related('client')
    buckets = {'Current': [], '1–30 days': [], '31–60 days': [], '61–90 days': [], '90+ days': []}
    for inv in invoices:
        buckets[inv.aging_bucket()].append(inv)
    bucket_totals = {k: sum(float(i.balance_due) for i in v) for k, v in buckets.items()}
    return render(request, 'billing/aging_report.html', {'buckets': buckets, 'bucket_totals': bucket_totals})


@login_required
def send_invoice_whatsapp(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    from notifications.services import send_whatsapp_message, send_email_notification
    from core.email_utils import send_invoice_email
    
    # Prepare WhatsApp message
    msg = (f"Dear {invoice.client.get_display_name()},\n\n"
           f"Invoice {invoice.invoice_number} from Taxman256.\n"
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
    inv = get_object_or_404(Invoice, pk=pk)
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
        
        clients = Client.objects.all()
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

    clients = Client.objects.all()
    result = {}
    for client in clients:
        update_client_outstanding(client)
        result[str(client.pk)] = str(client.total_outstanding)

    return JsonResponse({'clients': result})


@login_required
def other_income_list(request):
    """List all other income entries with filtering by category and date."""
    incomes = OtherIncome.objects.all().select_related('recorded_by')
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
    income = get_object_or_404(OtherIncome, pk=pk)
    return render(request, 'billing/otherincome_detail.html', {'income': income})


@login_required
def other_income_delete(request, pk):
    """Delete an other income entry."""
    income = get_object_or_404(OtherIncome, pk=pk)
    if request.method == 'POST':
        source_name = income.source_name
        income.delete()
        messages.success(request, f'✓ Deleted other income "{source_name}".')
        return redirect('billing:otherincome_list')
    
    return render(request, 'billing/otherincome_confirm_delete.html', {'income': income})
