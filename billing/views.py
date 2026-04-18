from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from .models import Invoice, Payment
from clients.models import Client


@login_required
def invoice_list(request):
    invoices = Invoice.objects.select_related('client', 'job_card').all()
    status = request.GET.get('status', '')
    q = request.GET.get('q', '')
    if status:
        invoices = invoices.filter(status=status)
    if q:
        invoices = invoices.filter(
            Q(invoice_number__icontains=q) | Q(client__full_name__icontains=q) |
            Q(client__trading_name__icontains=q))
    today = timezone.now().date()
    invoices.filter(status__in=['sent', 'partially_paid'], due_date__lt=today).update(status='overdue')
    agg = invoices.aggregate(total_invoiced=Sum('grand_total'), total_paid=Sum('amount_paid'))
    total_invoiced = agg['total_invoiced'] or 0
    total_paid = agg['total_paid'] or 0
    totals = {'total_invoiced': total_invoiced, 'total_paid': total_paid,
              'outstanding': total_invoiced - total_paid}
    return render(request, 'billing/invoice_list.html', {
        'invoices': invoices, 'status': status, 'q': q,
        'status_choices': Invoice.STATUS, 'totals': totals,
    })


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    payments = invoice.payments.order_by('-payment_date')
    return render(request, 'billing/invoice_detail.html', {'invoice': invoice, 'payments': payments})


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
            amount = Decimal(str(request.POST.get('amount', 0)))
            method = request.POST.get('method', 'cash')
            reference = request.POST.get('reference', '')
            Payment.objects.create(
                invoice=invoice, amount=amount, method=method,
                reference=reference, received_by=request.user)
            invoice.amount_paid = (invoice.amount_paid or Decimal('0')) + amount
            invoice.update_status()
            # Update client outstanding
            client = invoice.client
            out = Invoice.objects.filter(client=client).exclude(
                status__in=['paid', 'written_off']).aggregate(s=Sum('grand_total'))['s'] or Decimal('0')
            paid_sum = Invoice.objects.filter(client=client).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0')
            client.total_outstanding = max(Decimal('0'), out - paid_sum)
            client.save(update_fields=['total_outstanding'])
            messages.success(request, f'Payment of UGX {amount:,.0f} recorded.')
        except (InvalidOperation, TypeError) as e:
            messages.error(request, f'Invalid payment amount: {e}')
    return redirect('billing:detail', pk=pk)


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
    from notifications.services import send_whatsapp_message
    wa = invoice.client.get_whatsapp_number()
    if not wa:
        messages.error(request, 'Client has no WhatsApp number on file.')
        return redirect('billing:detail', pk=pk)
    msg = (f"Dear {invoice.client.get_display_name()},\n\n"
           f"Invoice {invoice.invoice_number} from Taxman256.\n"
           f"Total: UGX {invoice.grand_total:,.0f}\n"
           f"Balance Due: UGX {invoice.balance_due:,.0f}\n"
           f"Due Date: {invoice.due_date}\n\n"
           f"Pay to: +256785230670 (Mobile Money)\n"
           f"Ref: {invoice.invoice_number}\n\nThank you.")
    result = send_whatsapp_message(wa, msg, client=invoice.client,
                                   msg_type='invoice_delivery', triggered_by=request.user)
    invoice.sent_via_whatsapp = True
    invoice.sent_at = timezone.now()
    invoice.save(update_fields=['sent_via_whatsapp', 'sent_at'])
    messages.success(request, 'Invoice sent via WhatsApp.' if result else 'Logged (WhatsApp not configured — demo mode).')
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
