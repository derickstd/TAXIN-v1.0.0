from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Count
from services.models import ServiceType, JobCard
from billing.models import Invoice
from expenses.models import Expense
from clients.models import Client
from .models import ClientDocument
import calendar
from core.utils import paginate_queryset

@login_required
def documents_home(request):
    return redirect('documents:doc_list')


@login_required
def doc_list(request):
    client_pk = request.GET.get('client')
    docs = ClientDocument.objects.select_related('client', 'uploaded_by', 'job_card')
    if client_pk:
        docs = docs.filter(client_id=client_pk)
    page_obj = paginate_queryset(request, docs.order_by('-uploaded_at'), per_page=25)
    return render(request, 'documents/doc_list.html', {
        'docs': page_obj, 'page_obj': page_obj,
        'client_filter': client_pk,
        'doc_types': ClientDocument.DOC_TYPE,
        'clients': Client.objects.order_by('full_name'),
    })


@login_required
def doc_upload(request):
    if request.method == 'POST':
        client_id = request.POST.get('client')
        client = get_object_or_404(Client, pk=client_id)
        job_card_id = request.POST.get('job_card') or None
        f = request.FILES.get('file')
        if not f:
            messages.error(request, 'Please select a file to upload.')
            return redirect(request.META.get('HTTP_REFERER', 'documents:doc_list'))
        ClientDocument.objects.create(
            client=client,
            job_card_id=job_card_id,
            doc_type=request.POST.get('doc_type', 'other'),
            title=request.POST.get('title', f.name),
            file=f,
            period_label=request.POST.get('period_label', ''),
            notes=request.POST.get('notes', ''),
            uploaded_by=request.user,
        )
        messages.success(request, 'Document uploaded successfully.')
        next_url = request.POST.get('next') or 'documents:doc_list'
        return redirect(next_url)
    return redirect('documents:doc_list')


@login_required
def doc_delete(request, pk):
    doc = get_object_or_404(ClientDocument, pk=pk)
    if request.method == 'POST':
        doc.file.delete(save=False)
        doc.delete()
        messages.success(request, 'Document deleted.')
    return redirect(request.META.get('HTTP_REFERER', 'documents:doc_list'))

@login_required
def price_list(request):
    services = ServiceType.objects.filter(is_active=True).order_by('category','name')
    by_category = {}
    for s in services:
        cat = s.get_category_display()
        by_category.setdefault(cat, []).append(s)
    return render(request, 'documents/price_list.html', {
        'services': services,
        'by_category': by_category,
        'today': timezone.now().date(),
    })

@login_required
def client_statement(request, pk):
    client = get_object_or_404(Client, pk=pk)
    date_from = request.GET.get('from')
    date_to = request.GET.get('to')
    invoices = client.invoices.order_by('date_issued')
    if date_from:
        invoices = invoices.filter(date_issued__gte=date_from)
    if date_to:
        invoices = invoices.filter(date_issued__lte=date_to)
    total_invoiced = invoices.aggregate(s=Sum('grand_total'))['s'] or 0
    total_paid = invoices.aggregate(s=Sum('amount_paid'))['s'] or 0
    return render(request, 'documents/client_statement.html', {
        'client': client, 'invoices': invoices,
        'total_invoiced': total_invoiced, 'total_paid': total_paid,
        'balance': total_invoiced - total_paid,
        'today': timezone.now().date(),
        'date_from': date_from, 'date_to': date_to,
    })

@login_required
def monthly_report(request):
    today = timezone.now().date()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    years = list(range(today.year - 2, today.year + 2))
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]

    invoices = Invoice.objects.filter(date_issued__month=month, date_issued__year=year)
    expenses = Expense.objects.filter(expense_date__month=month, expense_date__year=year, status='approved')

    total_invoiced = invoices.aggregate(s=Sum('grand_total'))['s'] or 0
    total_collected = invoices.aggregate(s=Sum('amount_paid'))['s'] or 0
    total_expenses = expenses.aggregate(s=Sum('amount'))['s'] or 0
    collection_rate = round((float(total_collected)/float(total_invoiced)*100),1) if total_invoiced else 0

    top_clients = (Client.objects
        .filter(invoices__date_issued__month=month, invoices__date_issued__year=year)
        .annotate(revenue=Sum('invoices__grand_total'))
        .order_by('-revenue')[:10])

    exp_by_cat = expenses.values('category__name').annotate(total=Sum('amount')).order_by('-total')

    job_summary = {}
    for s,_ in JobCard.STATUS:
        cnt = JobCard.objects.filter(created_at__month=month, created_at__year=year, status=s).count()
        if cnt: job_summary[s] = cnt

    invoice_summary = {}
    for s,_ in Invoice.STATUS:
        cnt = invoices.filter(status=s).count()
        if cnt: invoice_summary[s] = cnt

    return render(request, 'documents/monthly_report.html', {
        'month': month, 'year': year,
        'month_name': calendar.month_name[month],
        'months': months, 'years': years,
        'total_invoiced': total_invoiced, 'total_collected': total_collected,
        'collection_rate': collection_rate,
        'total_expenses': total_expenses,
        'net_profit': total_collected - total_expenses,
        'top_clients': top_clients,
        'exp_by_cat': exp_by_cat,
        'job_summary': job_summary,
        'invoice_summary': invoice_summary,
        'today': today,
    })

@login_required
def audit_books(request):
    today = timezone.now().date()
    year = int(request.GET.get('year', today.year))
    years = list(range(today.year - 3, today.year + 2))

    total_revenue = Invoice.objects.filter(date_issued__year=year).aggregate(s=Sum('grand_total'))['s'] or 0
    total_collected = Invoice.objects.filter(date_issued__year=year).aggregate(s=Sum('amount_paid'))['s'] or 0
    outstanding = total_revenue - total_collected
    expenses = Expense.objects.filter(expense_date__year=year, status='approved')
    exp_by_cat = expenses.values('category__name').annotate(total=Sum('amount')).order_by('-total')
    total_expenses = expenses.aggregate(s=Sum('amount'))['s'] or 0
    gross_profit = total_collected - total_expenses

    return render(request, 'documents/audit_books.html', {
        'year': year, 'years': years, 'today': today,
        'total_revenue': total_revenue, 'total_collected': total_collected,
        'outstanding': outstanding, 'exp_by_cat': exp_by_cat,
        'total_expenses': total_expenses, 'gross_profit': gross_profit,
    })
