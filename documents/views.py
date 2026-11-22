from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.db.models import Q, Sum, Count
from django.views.decorators.http import require_http_methods, require_POST
from services.models import ServiceType, JobCard, JobCardLineItem
from billing.models import (
    BranchDailySummary, BranchDailyTransaction, Invoice, Payment, OtherIncome,
)
from expenses.models import Expense, ExpenseCategory
from clients.models import Client
from .models import (
    BranchAccountTransfer, BranchBalanceSheetEntry, ClientDocument,
)
import calendar
from datetime import date, timedelta
from decimal import Decimal
from core.utils import paginate_queryset
from core.branch_access import accessible_branches, scope_queryset
from core.branch_reporting import (
    branch_cash_summary, branch_comparison_for_user, company_branches_for_user,
)
from core.models import Branch
from .forms import (
    BranchAccountTransferEditForm, BranchAccountTransferForm,
    BranchBalanceSheetEntryForm, BranchDailySummaryForm,
    BranchDailyTransactionForm, LedgerExpenseEditForm,
    LedgerOtherIncomeEditForm, LedgerPaymentEditForm,
)
from .accounting import (
    branch_cash_account_balances, branch_cash_account_movements,
    latest_balance_sheet_entries,
)
from django.db import IntegrityError, transaction

@login_required
def documents_home(request):
    return redirect('documents:doc_list')


@login_required
def doc_list(request):
    client_pk = request.GET.get('client')
    docs = scope_queryset(
        request.user,
        ClientDocument.objects.select_related('client', 'uploaded_by', 'job_card'),
        branch_path='client__branch',
    )
    if client_pk:
        docs = docs.filter(client_id=client_pk)
    page_obj = paginate_queryset(request, docs.order_by('-uploaded_at'), per_page=25)
    return render(request, 'documents/doc_list.html', {
        'docs': page_obj, 'page_obj': page_obj,
        'client_filter': client_pk,
        'doc_types': ClientDocument.DOC_TYPE,
        'clients': scope_queryset(request.user, Client.objects.order_by('full_name')),
    })


@login_required
def doc_upload(request):
    if request.method == 'POST':
        client_id = request.POST.get('client')
        client = get_object_or_404(scope_queryset(request.user, Client.objects.all()), pk=client_id)
        job_card_id = request.POST.get('job_card') or None
        job_card = None
        if job_card_id:
            job_card = get_object_or_404(
                scope_queryset(request.user, JobCard.objects.all()),
                pk=job_card_id, client=client,
            )
        f = request.FILES.get('file')
        if not f:
            messages.error(request, 'Please select a file to upload.')
            return redirect(request.META.get('HTTP_REFERER', 'documents:doc_list'))
        ClientDocument.objects.create(
            client=client,
            job_card=job_card,
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
    doc = get_object_or_404(
        scope_queryset(request.user, ClientDocument.objects.all(), branch_path='client__branch'),
        pk=pk,
    )
    if request.method == 'POST':
        doc.file.delete(save=False)
        doc.delete()
        messages.success(request, 'Document deleted.')
    return redirect(request.META.get('HTTP_REFERER', 'documents:doc_list'))

@login_required
def price_list(request):
    services = scope_queryset(
        request.user, ServiceType.objects.filter(is_active=True), branch_path='branches',
    ).distinct().order_by('category', 'name')
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
    client = get_object_or_404(scope_queryset(request.user, Client.objects.all()), pk=pk)
    date_from = request.GET.get('from')
    date_to = request.GET.get('to')
    invoices = scope_queryset(
        request.user, client.invoices.all(),
    ).order_by('date_issued')
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

    invoices = scope_queryset(request.user, Invoice.objects.filter(date_issued__month=month, date_issued__year=year))
    expenses = scope_queryset(request.user, Expense.objects.filter(expense_date__month=month, expense_date__year=year, status='approved'))
    payments = scope_queryset(request.user, Payment.objects.filter(payment_date__month=month, payment_date__year=year))

    total_invoiced = invoices.aggregate(s=Sum('grand_total'))['s'] or 0
    total_collected = payments.aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_expenses = expenses.aggregate(s=Sum('amount'))['s'] or 0
    total_cash_inflow = total_collected
    total_cash_outflow = total_expenses
    cashflow_net_total = total_cash_inflow - total_cash_outflow
    collection_rate = round((float(total_collected)/float(total_invoiced)*100),1) if total_invoiced else 0

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    cash_in_by_date = {first_day + timedelta(days=i): Decimal('0') for i in range((last_day - first_day).days + 1)}
    cash_out_by_date = {day: Decimal('0') for day in cash_in_by_date}
    for payment in payments:
        cash_in_by_date[payment.payment_date] += payment.amount
    for expense in expenses:
        cash_out_by_date[expense.expense_date] += expense.amount

    cashflow_by_date = []
    running_balance = Decimal('0')
    current_day = first_day
    while current_day <= last_day:
        inflow = cash_in_by_date.get(current_day, Decimal('0'))
        outflow = cash_out_by_date.get(current_day, Decimal('0'))
        net = inflow - outflow
        running_balance += net
        cashflow_by_date.append({
            'date': current_day,
            'inflow': inflow,
            'outflow': outflow,
            'net': net,
            'balance': running_balance,
        })
        current_day += timedelta(days=1)

    cashflow_end_balance = cashflow_by_date[-1]['balance'] if cashflow_by_date else Decimal('0')

    top_clients = (scope_queryset(request.user, Client.objects
        .filter(invoices__date_issued__month=month, invoices__date_issued__year=year)
    )
        .annotate(revenue=Sum('invoices__grand_total'))
        .order_by('-revenue')[:10])

    exp_by_cat = expenses.values('category__name').annotate(total=Sum('amount')).order_by('-total')

    job_summary = {}
    for s,_ in JobCard.STATUS:
        cnt = scope_queryset(request.user, JobCard.objects.filter(
            created_at__month=month, created_at__year=year, status=s,
        )).count()
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
        'total_cash_inflow': total_cash_inflow,
        'total_cash_outflow': total_cash_outflow,
        'cashflow_net_total': cashflow_net_total,
        'cashflow_by_date': cashflow_by_date,
        'cashflow_end_balance': cashflow_end_balance,
        'net_profit': total_collected - total_expenses,
        'top_clients': top_clients,
        'exp_by_cat': exp_by_cat,
        'job_summary': job_summary,
        'invoice_summary': invoice_summary,
        'today': today,
    })


@login_required
def branch_daily_summaries(request):
    open_summary_modal = request.GET.get('open') == 'summary' or request.method == 'POST'
    branches = accessible_branches(request.user)
    if request.user.is_superuser:
        branches = Branch.objects.filter(is_active=True)
    branch_id = request.GET.get('branch') or request.POST.get('branch')
    selected_branch = None
    if branch_id:
        selected_branch = get_object_or_404(branches, pk=branch_id)
    elif branches.count() == 1:
        selected_branch = branches.first()

    raw_date = request.GET.get('date', '')
    try:
        business_date = date.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except ValueError:
        if request.GET.get('prefill') == 'summary':
            return JsonResponse({'error': 'Enter a valid business date.'}, status=400)
        business_date = timezone.localdate()
        messages.error(request, 'Invalid business date.')

    if request.GET.get('prefill') == 'summary':
        if not selected_branch:
            return JsonResponse({'error': 'Select a branch to load its balances.'}, status=400)
        if business_date > timezone.localdate():
            return JsonResponse(
                {'error': 'A daily summary cannot be dated in the future.'},
                status=400,
            )
        totals = branch_cash_summary(
            selected_branch, business_date, business_date,
        )
        opening_balance = totals['opening_cash']
        cash_inflow = totals['inflow']
        cash_outflow = totals['outflow']
        return JsonResponse({
            'opening_balance': str(opening_balance),
            'cash_inflow': str(cash_inflow),
            'cash_outflow': str(cash_outflow),
            'closing_balance': str(
                opening_balance + cash_inflow - cash_outflow,
            ),
        })

    existing = None
    if selected_branch:
        existing = BranchDailySummary.objects.filter(
            branch=selected_branch, business_date=business_date,
        ).first()
        if (
            existing and request.method == 'POST'
            and existing.submitted_by_id != request.user.pk
            and not request.user.is_manager_or_admin()
        ):
            messages.error(request, 'Only the original submitter or a branch manager can update this summary.')
            return redirect(
                f"{request.path}?branch={selected_branch.pk}&date={business_date.isoformat()}"
            )
        if existing and existing.reviewed_at:
            if request.user != existing.submitted_by and not request.user.is_manager_or_admin():
                messages.error(request, 'This summary is locked after review.')
                existing = None
            elif request.method == 'POST':
                messages.error(request, 'This summary has been reviewed and is locked.')
                existing = None
                form = BranchDailySummaryForm(
                    request.POST, branches=branches,
                )
                form.add_error(None, 'Reviewed summaries cannot be changed.')
                return render(request, 'documents/branch_daily_summaries.html', {
                    'branches': branches, 'selected_branch': selected_branch,
                    'summaries': scope_queryset(
                        request.user, BranchDailySummary.objects.select_related(
                            'branch', 'submitted_by', 'updated_by', 'reviewed_by',
                        ),
                    ).order_by('-business_date')[:60],
                    'form': form, 'business_date': business_date,
                    'open_summary_modal': True,
                })

    if request.method == 'POST':
        form = BranchDailySummaryForm(
            request.POST, instance=existing, branches=branches,
        )
        if form.is_valid():
            summary = form.save(commit=False)
            summary.submitted_by = existing.submitted_by if existing else request.user
            summary.updated_by = request.user
            try:
                with transaction.atomic():
                    summary.save()
                messages.success(request, 'Daily branch summary saved.')
                return redirect(
                    f"{request.path}?branch={summary.branch_id}&date={summary.business_date.isoformat()}"
                )
            except IntegrityError:
                form.add_error(None, 'A summary for this branch and date was just saved by another user.')
    else:
        initial = {'business_date': business_date}
        if selected_branch:
            initial['branch'] = selected_branch
            daily_totals = branch_cash_summary(
                selected_branch, business_date, business_date,
            )
            initial.update({
                'opening_balance': daily_totals['opening_cash'],
                'cash_inflow': daily_totals['inflow'],
                'cash_outflow': daily_totals['outflow'],
                'closing_balance': (
                    daily_totals['opening_cash']
                    + daily_totals['inflow']
                    - daily_totals['outflow']
                ),
            })
        form = BranchDailySummaryForm(
            instance=existing, initial=initial, branches=branches,
        )

    summaries = scope_queryset(
        request.user,
        BranchDailySummary.objects.select_related(
            'branch', 'submitted_by', 'updated_by', 'reviewed_by',
        ),
    ).order_by('-business_date')[:60]
    return render(request, 'documents/branch_daily_summaries.html', {
        'branches': branches,
        'selected_branch': selected_branch,
        'summaries': summaries,
        'form': form,
        'business_date': business_date,
        'open_summary_modal': open_summary_modal,
    })


@login_required
def branch_daily_ledger(request):
    return _branch_daily_ledger(request)


@login_required
def branch_daily_expense(request):
    return _branch_daily_ledger(request, expense_only=True)


_LEDGER_RECORD_MODELS = {
    'daily_entry': BranchDailyTransaction,
    'payment': Payment,
    'other_income': OtherIncome,
    'expense': Expense,
    'transfer': BranchAccountTransfer,
    'summary': BranchDailySummary,
}
_LEDGER_RECORD_DATE_FIELDS = {
    'daily_entry': 'business_date',
    'payment': 'payment_date',
    'other_income': 'income_date',
    'expense': 'expense_date',
    'transfer': 'transfer_date',
    'summary': 'business_date',
}
_LEDGER_RECORD_LABELS = {
    'daily_entry': 'Branch transaction',
    'payment': 'Payment',
    'other_income': 'Other income',
    'expense': 'Expense',
    'transfer': 'Account transfer',
    'summary': 'Daily summary',
}


def _can_manage_ledger_transactions(user):
    return user.is_superuser or user.role in ('admin', 'ceo')


def _ledger_visible_branches(user):
    if user.is_superuser:
        return Branch.objects.filter(is_active=True)
    company_id = user.company_id
    if not company_id and user.branch_id:
        company_id = Branch.objects.filter(
            pk=user.branch_id, is_active=True,
        ).values_list('company_id', flat=True).first()
    if company_id:
        return Branch.objects.filter(company_id=company_id, is_active=True)
    return accessible_branches(user)


def _ledger_accessible_branches(user):
    if _can_manage_ledger_transactions(user):
        return _ledger_visible_branches(user)
    return accessible_branches(user)


def _get_ledger_record(user, record_type, pk, *, for_update=False):
    model = _LEDGER_RECORD_MODELS.get(record_type)
    if model is None:
        raise Http404
    queryset = model.objects.all()
    if for_update:
        queryset = queryset.select_for_update()
    return get_object_or_404(
        queryset.filter(branch__in=_ledger_accessible_branches(user)),
        pk=pk,
    )


def _ledger_record_branch_date(record_type, record, values=None):
    values = values or {}
    date_field = _LEDGER_RECORD_DATE_FIELDS[record_type]
    return (
        values.get('branch', record.branch),
        values.get(date_field, getattr(record, date_field)),
    )


def _has_reviewed_ledger_day(
    branch, business_date, *, exclude_summary_id=None, for_update=False,
):
    if not branch or not business_date:
        return False
    summaries = BranchDailySummary.objects.filter(
        branch=branch,
        business_date=business_date,
    )
    if exclude_summary_id:
        summaries = summaries.exclude(pk=exclude_summary_id)
    if for_update:
        summaries = summaries.select_for_update()
    return summaries.filter(reviewed_at__isnull=False).exists()


def _ledger_record_is_locked(record_type, record, *, for_update=False):
    if record_type == 'summary' and record.reviewed_at:
        return True
    branch, business_date = _ledger_record_branch_date(record_type, record)
    return _has_reviewed_ledger_day(
        branch, business_date, for_update=for_update,
    )


def _ledger_edit_form(record_type, request, record):
    data = request.POST if request.method == 'POST' else None
    if record_type == 'daily_entry':
        return BranchDailyTransactionForm(
            data,
            instance=record,
            branches=_ledger_accessible_branches(request.user),
            expense_only=(
                record.direction == 'outflow'
                and record.category == 'operating_expense'
            ),
        )
    if record_type == 'payment':
        return LedgerPaymentEditForm(data, instance=record)
    if record_type == 'other_income':
        return LedgerOtherIncomeEditForm(data, instance=record)
    if record_type == 'expense':
        return LedgerExpenseEditForm(data, instance=record)
    if record_type == 'transfer':
        return BranchAccountTransferEditForm(
            data, instance=record, branches=_ledger_accessible_branches(request.user),
        )
    if record_type == 'summary':
        return BranchDailySummaryForm(
            data, instance=record, branches=_ledger_accessible_branches(request.user),
        )
    raise Http404


def _ledger_redirect(branch, business_date, user=None):
    url = f'{reverse("documents:branch_daily_ledger")}?'
    if user and (
        user.is_superuser
        or (user.role in ('admin', 'ceo') and user.company_id)
    ):
        return f'{url}date={business_date.isoformat()}'
    return f'{url}branch={branch.pk}&date={business_date.isoformat()}'


@login_required
@require_http_methods(['GET', 'POST'])
def ledger_transaction_edit(request, record_type, pk):
    if not _can_manage_ledger_transactions(request.user):
        raise PermissionDenied

    record = _get_ledger_record(request.user, record_type, pk)
    if request.method == 'POST':
        form = None
        try:
            with transaction.atomic():
                record = _get_ledger_record(
                    request.user, record_type, pk, for_update=True,
                )
                form = _ledger_edit_form(record_type, request, record)
                if _ledger_record_is_locked(
                    record_type, record, for_update=True,
                ):
                    form.add_error(
                        None,
                        'This branch day has been reviewed and locked.',
                    )
                elif form.is_valid():
                    target_branch, target_date = _ledger_record_branch_date(
                        record_type, record, form.cleaned_data,
                    )
                    exclude_summary_id = (
                        record.pk if record_type == 'summary' else None
                    )
                    if _has_reviewed_ledger_day(
                        target_branch,
                        target_date,
                        exclude_summary_id=exclude_summary_id,
                        for_update=True,
                    ):
                        form.add_error(
                            None,
                            'The destination branch day has been reviewed and locked.',
                        )
                    else:
                        updated_record = form.save(commit=False)
                        updated_record._audit_actor = request.user
                        if record_type == 'summary':
                            updated_record.updated_by = request.user
                        if (
                            record_type == 'expense'
                            and updated_record.status == 'approved'
                            and form.changed_data
                        ):
                            updated_record.status = 'submitted'
                            updated_record.approved_by = None
                        updated_record.save()
                        form.save_m2m()
                        branch, business_date = _ledger_record_branch_date(
                            record_type, updated_record,
                        )
                        messages.success(
                            request,
                            f'{_LEDGER_RECORD_LABELS[record_type]} updated.',
                        )
                        return redirect(
                            _ledger_redirect(branch, business_date, request.user),
                        )
        except IntegrityError:
            if form is None:
                form = _ledger_edit_form(record_type, request, record)
            form.add_error(
                None,
                'This reference or branch/date is already in use.',
            )

    else:
        if _ledger_record_is_locked(record_type, record):
            messages.error(request, 'This branch day has been reviewed and locked.')
            branch, business_date = _ledger_record_branch_date(record_type, record)
            return redirect(
                _ledger_redirect(branch, business_date, request.user),
            )
        form = _ledger_edit_form(record_type, request, record)

    return render(request, 'documents/ledger_transaction_edit.html', {
        'form': form,
        'record': record,
        'record_type': record_type,
        'record_label': _LEDGER_RECORD_LABELS[record_type],
        'return_url': _ledger_redirect(
            record.branch,
            getattr(record, _LEDGER_RECORD_DATE_FIELDS[record_type]),
            request.user,
        ),
    })


@login_required
@require_POST
def ledger_transaction_delete(request, record_type, pk):
    if not _can_manage_ledger_transactions(request.user):
        raise PermissionDenied

    try:
        with transaction.atomic():
            record = _get_ledger_record(
                request.user, record_type, pk, for_update=True,
            )
            branch, business_date = _ledger_record_branch_date(
                record_type, record,
            )
            if _ledger_record_is_locked(
                record_type, record, for_update=True,
            ):
                messages.error(request, 'This branch day has been reviewed and locked.')
            else:
                record._audit_actor = request.user
                record.delete()
                messages.success(
                    request,
                    f'{_LEDGER_RECORD_LABELS[record_type]} deleted.',
                )
    except IntegrityError:
        messages.error(request, 'This transaction could not be deleted.')

    return redirect(_ledger_redirect(branch, business_date, request.user))


def _branch_daily_ledger(request, expense_only=False):
    branches = _ledger_visible_branches(request.user)
    external_branches = _ledger_accessible_branches(
        request.user,
    ).filter(external_reporting=True)
    branch_id = request.GET.get('branch') or request.POST.get('branch')
    selected_branch = get_object_or_404(branches, pk=branch_id) if branch_id else None
    can_manage_transactions = _can_manage_ledger_transactions(request.user)
    if (
        not selected_branch
        and branches.count() == 1
        and not can_manage_transactions
    ):
        selected_branch = branches.first()
    explicitly_selected_branch = bool(request.GET.get('branch'))

    requested_period = request.GET.get('period') or request.POST.get('period', 'today')
    raw_date = request.GET.get('date', '')
    period_options = [
        ('today', 'Today'),
        ('yesterday', 'Yesterday'),
        ('this_week', 'This week'),
        ('this_month', 'This month'),
        ('last_month', 'Last month'),
    ]
    valid_periods = {value for value, _ in period_options}
    if requested_period not in valid_periods and requested_period != 'custom':
        messages.error(request, 'Invalid ledger period. Showing today instead.')
        requested_period = 'today'
    if requested_period == 'custom' and not raw_date:
        raw_date = request.POST.get('business_date', '')

    today = timezone.localdate()
    month_start = date(today.year, today.month, 1)
    if requested_period == 'yesterday':
        date_from = date_to = today - timedelta(days=1)
    elif requested_period == 'this_week':
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif requested_period == 'this_month':
        date_from, date_to = month_start, today
    elif requested_period == 'last_month':
        date_to = month_start - timedelta(days=1)
        date_from = date(date_to.year, date_to.month, 1)
    else:
        date_from = date_to = today

    period = requested_period
    if raw_date:
        try:
            date_from = date_to = date.fromisoformat(raw_date)
            period = 'custom'
        except ValueError:
            messages.error(request, 'Invalid transaction date. Showing today instead.')
            date_from = date_to = today
            period = 'today'

    business_date = date_to

    initial = {'business_date': business_date}
    if (
        selected_branch
        and selected_branch.external_reporting
        and external_branches.filter(pk=selected_branch.pk).exists()
        and (not can_manage_transactions or explicitly_selected_branch)
    ):
        initial['branch'] = selected_branch
    requested_direction = request.GET.get('direction')
    requested_category = request.GET.get('category')
    if expense_only:
        initial.update({
            'direction': 'outflow',
            'category': 'operating_expense',
        })
    else:
        if requested_direction in dict(BranchDailyTransaction.DIRECTION):
            initial['direction'] = requested_direction
        if requested_category in dict(BranchDailyTransaction.CATEGORY):
            initial['category'] = requested_category
    open_transaction_modal = request.GET.get('open') == 'transaction' or request.method == 'POST'
    if request.method == 'POST':
        form = BranchDailyTransactionForm(
            request.POST, branches=external_branches,
            expense_only=expense_only,
            require_branch_selection=can_manage_transactions,
        )
        if form.is_valid():
            branch = form.cleaned_data['branch']
            entry_date = form.cleaned_data['business_date']
            try:
                with transaction.atomic():
                    summary = BranchDailySummary.objects.select_for_update().filter(
                        branch=branch, business_date=entry_date,
                    ).first()
                    if summary and summary.reviewed_at:
                        form.add_error(None, 'This day has been reviewed and locked.')
                    else:
                        entry = form.save(commit=False)
                        entry.entered_by = request.user
                        entry.save()
                if not form.errors:
                    messages.success(request, 'Daily transaction recorded.')
                    return redirect(
                        _ledger_redirect(branch, entry_date, request.user),
                    )
            except IntegrityError:
                form.add_error(
                    'reference',
                    'This reference has already been recorded for the branch and date.',
                )
    else:
        form = BranchDailyTransactionForm(
            initial=initial, branches=external_branches,
            expense_only=expense_only,
            require_branch_selection=can_manage_transactions,
        )

    selected_branches = branches
    if selected_branch:
        selected_branches = selected_branches.filter(pk=selected_branch.pk)
    internal_branches = selected_branches.filter(external_reporting=False)
    summaries = list(
        BranchDailySummary.objects.filter(
            branch__in=selected_branches,
            business_date__range=(date_from, date_to),
        ).select_related('branch', 'submitted_by', 'reviewed_by')
    )
    summary_keys = {
        (summary.branch_id, summary.business_date) for summary in summaries
    }
    locked_summary_keys = {
        (summary.branch_id, summary.business_date)
        for summary in summaries if summary.reviewed_at
    }
    external_entries = list(
        BranchDailyTransaction.objects.filter(
            branch__in=selected_branches.filter(external_reporting=True),
            business_date__range=(date_from, date_to),
        ).select_related('branch', 'entered_by', 'expense_category')
    )
    zero = Decimal('0')
    ledger_totals_by_branch = {}
    for entry in external_entries:
        totals = ledger_totals_by_branch.setdefault(
            (entry.branch_id, entry.business_date),
            {'inflow': zero, 'outflow': zero},
        )
        key = 'inflow' if entry.direction == 'inflow' else 'outflow'
        totals[key] += entry.amount
    reconciliations = []
    for summary in summaries:
        ledger_totals = ledger_totals_by_branch.get(
            (summary.branch_id, summary.business_date),
        )
        if summary.branch.external_reporting and ledger_totals is not None:
            reconciliations.append({
                'summary': summary,
                'ledger_inflow': ledger_totals['inflow'],
                'ledger_outflow': ledger_totals['outflow'],
                'totals_match': (
                    summary.cash_inflow == ledger_totals['inflow']
                    and summary.cash_outflow == ledger_totals['outflow']
                ),
                'closing_variance': summary.closing_balance - (
                    summary.opening_balance
                    + ledger_totals['inflow'] - ledger_totals['outflow']
                ),
            })
    transactions = []

    def user_label(user):
        return (user.get_full_name() or user.username) if user else '—'

    def append_transaction(
        *, branch, business_date, created_at, pk, entry_type, description, method, reference,
        recorded_by, inflow=zero, outflow=zero, counts_in_totals=True,
        record_type=None, actions_available=True, transfer_amount=zero,
    ):
        transactions.append({
            'branch': branch,
            'business_date': business_date,
            'created_at': created_at,
            'id': pk,
            'type': entry_type,
            'description': description,
            'method': method,
            'reference': reference or '—',
            'recorded_by': recorded_by,
            'inflow': inflow,
            'outflow': outflow,
            'transfer_amount': transfer_amount,
            'counts_in_totals': counts_in_totals,
            'record_type': record_type,
            'actions_locked': bool(
                record_type
                and (branch.pk, business_date) in locked_summary_keys
            ),
            'can_edit': bool(
                can_manage_transactions
                and record_type
                and actions_available
                and (branch.pk, business_date) not in locked_summary_keys
            ),
        })

    for entry in external_entries:
        append_transaction(
            branch=entry.branch,
            business_date=entry.business_date,
            created_at=entry.created_at,
            pk=entry.pk,
            entry_type=entry.display_category,
            description=entry.description,
            method=entry.get_account_display(),
            reference=entry.reference,
            recorded_by=user_label(entry.entered_by),
            inflow=entry.amount if entry.direction == 'inflow' else zero,
            outflow=entry.amount if entry.direction == 'outflow' else zero,
            record_type='daily_entry',
        )

    payments = Payment.objects.filter(
        branch__in=internal_branches,
        payment_date__range=(date_from, date_to),
    ).select_related('branch', 'invoice__client', 'client', 'received_by')
    for payment in payments:
        if (payment.branch_id, payment.payment_date) in summary_keys:
            continue
        if payment.invoice_id:
            customer = payment.client.get_display_name() if payment.client_id else 'Customer'
            description = f'{payment.invoice.invoice_number} — {customer}'
        else:
            description = payment.client.get_display_name() if payment.client_id else 'Direct payment'
        append_transaction(
            branch=payment.branch,
            business_date=payment.payment_date,
            created_at=payment.created_at,
            pk=payment.pk,
            entry_type='Customer payment',
            description=description,
            method=payment.get_method_display(),
            reference=payment.reference,
            recorded_by=user_label(payment.received_by),
            inflow=payment.amount,
            record_type='payment',
        )

    incomes = OtherIncome.objects.filter(
        branch__in=internal_branches,
        income_date__range=(date_from, date_to),
    ).select_related('branch', 'recorded_by')
    for income in incomes:
        if (income.branch_id, income.income_date) in summary_keys:
            continue
        append_transaction(
            branch=income.branch,
            business_date=income.income_date,
            created_at=income.created_at,
            pk=income.pk,
            entry_type=income.get_category_display(),
            description=income.source_name,
            method=income.get_collection_method_display(),
            reference=income.reference,
            recorded_by=user_label(income.recorded_by),
            inflow=income.amount,
            record_type='other_income',
        )

    expenses = Expense.objects.filter(
        branch__in=internal_branches,
        expense_date__range=(date_from, date_to),
        status__in=('submitted', 'approved'),
    ).select_related('branch', 'category', 'paid_by', 'created_by')
    for expense in expenses:
        if (expense.branch_id, expense.expense_date) in summary_keys:
            continue
        description = expense.description
        if expense.category_id:
            description = f'{expense.category.name} — {description}'
        append_transaction(
            branch=expense.branch,
            business_date=expense.expense_date,
            created_at=expense.created_at,
            pk=expense.pk,
            entry_type=(
                'Approved expense' if expense.status == 'approved'
                else 'Pending expense'
            ),
            description=description,
            method=expense.get_payment_method_display(),
            reference=expense.reference,
            recorded_by=user_label(expense.paid_by or expense.created_by),
            outflow=expense.amount,
            counts_in_totals=expense.status == 'approved',
            record_type='expense',
        )

    for transfer in BranchAccountTransfer.objects.filter(
        branch__in=selected_branches,
        transfer_date__range=(date_from, date_to),
    ).select_related('branch', 'entered_by'):
        account_labels = dict(BranchAccountTransfer.ACCOUNT_CHOICES)
        source_label = account_labels[transfer.source_account]
        destination_label = account_labels[transfer.destination_account]
        transfer_type = (
            'Bank deposit transfer'
            if transfer.destination_account == 'bank'
            else 'Bank withdrawal transfer'
        )
        common = {
            'branch': transfer.branch,
            'business_date': transfer.transfer_date,
            'created_at': transfer.created_at,
            'pk': transfer.pk,
            'entry_type': transfer_type,
            'method': 'Internal transfer',
            'reference': transfer.reference,
            'recorded_by': user_label(transfer.entered_by),
            'counts_in_totals': False,
            'record_type': 'transfer',
        }
        append_transaction(
            **common,
            description=(
                f'{source_label} to {destination_label} — '
                f'{transfer.description}'
            ),
            transfer_amount=transfer.amount,
        )

    external_entry_days = {
        (entry.branch_id, entry.business_date) for entry in external_entries
    }
    for summary in summaries:
        if (
            summary.branch.external_reporting
            and (summary.branch_id, summary.business_date) in external_entry_days
        ):
            continue
        append_transaction(
            branch=summary.branch,
            business_date=summary.business_date,
            created_at=summary.created_at,
            pk=summary.pk,
            entry_type='Branch daily summary',
            description=f'{summary.branch.name} end-of-day summary',
            method='End-of-day summary',
            reference='',
            recorded_by=user_label(summary.submitted_by),
            inflow=summary.cash_inflow,
            outflow=summary.cash_outflow,
            record_type='summary',
        )

    transactions.sort(
        key=lambda item: (
            item['business_date'], item['created_at'],
            item['branch'].name, item['id'],
        ),
        reverse=True,
    )
    total_inflow = sum(
        (item['inflow'] for item in transactions if item['counts_in_totals']),
        zero,
    )
    total_outflow = sum(
        (item['outflow'] for item in transactions if item['counts_in_totals']),
        zero,
    )
    transaction_page = Paginator(transactions, 50).get_page(request.GET.get('page'))

    return render(request, 'documents/branch_daily_ledger.html', {
        'branches': branches,
        'external_branches': external_branches,
        'selected_branch': selected_branch,
        'business_date': business_date,
        'date_from': date_from,
        'date_to': date_to,
        'period': period,
        'period_options': period_options,
        'period_label': (
            'Selected date' if period == 'custom'
            else dict(period_options)[period]
        ),
        'form': form,
        'transactions': transaction_page,
        'total_inflow': total_inflow,
        'total_outflow': total_outflow,
        'net_movement': total_inflow - total_outflow,
        'reconciliations': reconciliations,
        'can_review_summary': request.user.is_manager_or_admin(),
        'can_manage_transactions': can_manage_transactions,
        'open_transaction_modal': open_transaction_modal,
        'category_directions': BranchDailyTransaction.CATEGORY_DIRECTIONS,
        'expense_only': expense_only,
    })


@login_required
def review_branch_daily_summary(request, pk):
    if request.method != 'POST' or not request.user.is_manager_or_admin():
        messages.error(request, 'Only branch managers and leadership can review summaries.')
        return redirect('documents:branch_daily_summaries')
    with transaction.atomic():
        summary = get_object_or_404(
            scope_queryset(
                request.user, BranchDailySummary.objects.select_for_update(),
            ),
            pk=pk,
        )
        if summary.reviewed_at:
            messages.info(request, 'This summary has already been reviewed.')
        else:
            ledger_totals = BranchDailyTransaction.objects.filter(
                branch=summary.branch, business_date=summary.business_date,
            ).values('direction').annotate(total=Sum('amount'))
            totals = {item['direction']: item['total'] for item in ledger_totals}
            has_ledger_entries = bool(totals)
            if summary.branch.external_reporting and has_ledger_entries and (
                summary.cash_inflow != totals.get('inflow', Decimal('0'))
                or summary.cash_outflow != totals.get('outflow', Decimal('0'))
            ):
                messages.error(
                    request,
                    'Daily summary totals must match the ledger transactions before review.',
                )
            else:
                summary.reviewed_by = request.user
                summary.reviewed_at = timezone.now()
                summary.save(update_fields=['reviewed_by', 'reviewed_at', 'updated_at'])
                messages.success(request, 'Daily summary reviewed and locked.')
    return redirect(
        f"{reverse('documents:branch_daily_summaries')}?branch={summary.branch_id}"
    )


@login_required
def financial_reports(request):
    return _financial_report(request, 'cash_flow')


@login_required
def balance_sheet_report(request):
    branches = company_branches_for_user(request.user).order_by('name')
    if request.method == 'POST':
        if not request.user.is_manager_or_admin():
            messages.error(request, 'Only branch managers and leadership can update balance-sheet accounts.')
            return redirect('documents:balance_sheet_report')
        form = BranchBalanceSheetEntryForm(request.POST, branches=branches)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.entered_by = request.user
            entry.save()
            messages.success(request, 'Balance-sheet account saved.')
            return redirect(
                f"{reverse('documents:balance_sheet_report')}?"
                f"branch={entry.branch_id}&from={entry.as_of_date.isoformat()}&"
                f"to={entry.as_of_date.isoformat()}"
            )
    else:
        form = None
    return _financial_report(
        request, 'balance_sheet', balance_sheet_entry_form=form,
    )


@login_required
def branch_account_transfer(request):
    popover_mode = request.GET.get('popover') == '1'
    branches = accessible_branches(request.user)
    if request.user.is_superuser:
        branches = Branch.objects.filter(is_active=True)
    branch_id = request.GET.get('branch') or request.POST.get('branch')
    selected_branch = get_object_or_404(branches, pk=branch_id) if branch_id else None
    if selected_branch is None and branches.count() == 1:
        selected_branch = branches.first()
    initial = {'transfer_date': timezone.localdate()}
    if selected_branch:
        initial['branch'] = selected_branch

    if request.method == 'POST':
        form = BranchAccountTransferForm(request.POST, branches=branches)
        if form.is_valid():
            transfer = form.save(commit=False)
            transfer.entered_by = request.user
            bank_charges = form.cleaned_data['bank_charges']
            try:
                with transaction.atomic():
                    summary = BranchDailySummary.objects.select_for_update().filter(
                        branch=transfer.branch,
                        business_date=transfer.transfer_date,
                    ).first()
                    if summary and summary.reviewed_at:
                        form.add_error(None, 'This day has been reviewed and locked.')
                    else:
                        transfer.save()
                        if bank_charges:
                            category, _ = ExpenseCategory.objects.get_or_create(
                                name='Bank Charges',
                            )
                            transfer_identifier = (
                                transfer.reference or f'#{transfer.pk}'
                            )
                            Expense.objects.create(
                                expense_date=transfer.transfer_date,
                                category=category,
                                description=(
                                    'Bank charges for account transfer '
                                    f'{transfer_identifier}'
                                ),
                                amount=bank_charges,
                                paid_by=request.user,
                                payment_method='bank_transfer',
                                reference=(
                                    transfer.reference
                                    or f'BANK-CHARGE-{transfer.pk}'
                                ),
                                status='submitted',
                                branch=transfer.branch,
                                created_by=request.user,
                            )
                if not form.errors:
                    transfer_label = (
                        'Bank deposit'
                        if transfer.destination_account == 'bank'
                        else 'Bank withdrawal'
                    )
                    charge_note = (
                        f' Bank charges of UGX {bank_charges:,.2f} '
                        'were recorded as an expense.'
                        if bank_charges else ''
                    )
                    if (
                        popover_mode
                        and request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    ):
                        return JsonResponse({
                            'message': f'{transfer_label} recorded.{charge_note}',
                        })
                    messages.success(
                        request,
                        f'{transfer_label} recorded as an account transfer.{charge_note}',
                    )
                    return redirect(
                        f"{reverse('documents:branch_account_statement')}?"
                        f"branch={transfer.branch_id}&from={transfer.transfer_date.isoformat()}&"
                        f"to={transfer.transfer_date.isoformat()}"
                    )
            except IntegrityError:
                form.add_error(
                    'reference',
                    'This reference has already been recorded for the branch and date.',
                )
    else:
        form = BranchAccountTransferForm(
            initial=initial, branches=branches,
        )

    context = {
        'form': form,
        'branches': branches,
        'selected_branch': selected_branch,
    }
    if popover_mode:
        return render(
            request,
            'documents/partials/branch_account_transfer_popover.html',
            context,
            status=400 if request.method == 'POST' and form.errors else 200,
        )
    return render(request, 'documents/branch_account_transfer.html', context)


@login_required
def branch_account_statement(request, bank_only=False):
    today = timezone.localdate()
    month_start = date(today.year, today.month, 1)
    try:
        date_from = date.fromisoformat(request.GET.get('from', '')) if request.GET.get('from') else month_start
        date_to = date.fromisoformat(request.GET.get('to', '')) if request.GET.get('to') else today
    except ValueError:
        messages.error(request, 'Invalid statement dates. Showing the current month instead.')
        date_from, date_to = month_start, today
    if date_from > date_to:
        messages.error(request, 'The start date must be on or before the end date.')
        date_from, date_to = month_start, today

    branches = accessible_branches(request.user).order_by('name')
    branch_id = request.GET.get('branch')
    selected_branch = get_object_or_404(branches, pk=branch_id) if branch_id else None
    if selected_branch is None and branches.count() == 1:
        selected_branch = branches.first()
    statement_branches = branches
    if selected_branch:
        statement_branches = statement_branches.filter(pk=selected_branch.pk)

    summaries = list(BranchDailySummary.objects.filter(
        branch__in=statement_branches,
        business_date__range=(date_from, date_to),
    ).select_related('branch', 'submitted_by'))
    summary_dates = {
        (summary.branch_id, summary.business_date) for summary in summaries
    }
    ledger_entries = list(BranchDailyTransaction.objects.filter(
        branch__in=statement_branches.filter(external_reporting=True),
        business_date__range=(date_from, date_to),
    ).select_related('branch', 'entered_by', 'expense_category'))
    ledger_dates = {
        (entry.branch_id, entry.business_date) for entry in ledger_entries
    }
    internal_branches = statement_branches.filter(external_reporting=False)
    rows = []

    def append_row(
        *, branch, transaction_date, account, description, reference,
        recorded_by, inflow=Decimal('0'), outflow=Decimal('0'),
        balance=None, entry_type='Transaction',
    ):
        rows.append({
            'branch': branch,
            'date': transaction_date,
            'account': account,
            'description': description,
            'reference': reference or '—',
            'recorded_by': recorded_by or '—',
            'inflow': inflow,
            'outflow': outflow,
            'balance': balance,
            'entry_type': entry_type,
        })

    for payment in Payment.objects.filter(
        branch__in=internal_branches,
        payment_date__range=(date_from, date_to),
    ).select_related('branch', 'client', 'invoice', 'received_by'):
        if (payment.branch_id, payment.payment_date) in summary_dates:
            continue
        append_row(
            branch=payment.branch,
            transaction_date=payment.payment_date,
            account=(
                'Bank' if payment.method == 'bank_transfer'
                else payment.get_payment_method_display()
            ),
            description=(
                payment.client.get_display_name()
                if payment.client_id else 'Customer payment'
            ),
            reference=payment.reference,
            recorded_by=(
                payment.received_by.get_full_name() or payment.received_by.username
                if payment.received_by_id else '—'
            ),
            inflow=payment.amount,
        )

    for income in OtherIncome.objects.filter(
        branch__in=internal_branches,
        income_date__range=(date_from, date_to),
    ).select_related('branch', 'recorded_by'):
        if (income.branch_id, income.income_date) in summary_dates:
            continue
        append_row(
            branch=income.branch,
            transaction_date=income.income_date,
            account=(
                'Bank' if income.collection_method == 'bank_transfer'
                else income.get_collection_method_display()
            ),
            description=income.source_name,
            reference=income.reference,
            recorded_by=(
                income.recorded_by.get_full_name() or income.recorded_by.username
                if income.recorded_by_id else '—'
            ),
            inflow=income.amount,
        )

    for expense in Expense.objects.filter(
        branch__in=internal_branches,
        expense_date__range=(date_from, date_to),
        status='approved',
    ).select_related('branch', 'category', 'paid_by', 'created_by'):
        if (expense.branch_id, expense.expense_date) in summary_dates:
            continue
        append_row(
            branch=expense.branch,
            transaction_date=expense.expense_date,
            account=(
                'Bank' if expense.payment_method == 'bank_transfer'
                else expense.get_payment_method_display()
            ),
            description=(
                f'{expense.category.name} — {expense.description}'
                if expense.category_id else expense.description
            ),
            reference=expense.reference,
            recorded_by=(
                expense.paid_by.get_full_name() or expense.paid_by.username
                if expense.paid_by_id
                else expense.created_by.get_full_name() or expense.created_by.username
                if expense.created_by_id else '—'
            ),
            outflow=expense.amount,
        )

    for entry in ledger_entries:
        append_row(
            branch=entry.branch,
            transaction_date=entry.business_date,
            account=entry.get_account_display(),
            description=f'{entry.display_category} — {entry.description}',
            reference=entry.reference,
            recorded_by=(
                entry.entered_by.get_full_name() or entry.entered_by.username
            ),
            inflow=entry.amount if entry.direction == 'inflow' else Decimal('0'),
            outflow=entry.amount if entry.direction == 'outflow' else Decimal('0'),
        )

    for summary in summaries:
        if (
            summary.branch.external_reporting
            and (summary.branch_id, summary.business_date) in ledger_dates
        ):
            continue
        append_row(
            branch=summary.branch,
            transaction_date=summary.business_date,
            account='Cash at hand (summary)',
            description='End-of-day summary; account split was not recorded',
            reference='',
            recorded_by=(
                summary.submitted_by.get_full_name() or summary.submitted_by.username
                if summary.submitted_by_id else '—'
            ),
            inflow=summary.cash_inflow,
            outflow=summary.cash_outflow,
            entry_type='Daily summary',
        )

    for transfer in BranchAccountTransfer.objects.filter(
        branch__in=statement_branches,
        transfer_date__range=(date_from, date_to),
    ).select_related('branch', 'entered_by'):
        actor = transfer.entered_by.get_full_name() or transfer.entered_by.username
        account_labels = dict(BranchAccountTransfer.ACCOUNT_CHOICES)
        append_row(
            branch=transfer.branch,
            transaction_date=transfer.transfer_date,
            account=account_labels[transfer.source_account],
            description=(
                f'Transfer to {account_labels[transfer.destination_account]} — '
                f'{transfer.description}'
            ),
            reference=transfer.reference,
            recorded_by=actor,
            outflow=transfer.amount,
            entry_type='Transfer',
        )
        append_row(
            branch=transfer.branch,
            transaction_date=transfer.transfer_date,
            account=account_labels[transfer.destination_account],
            description=(
                f'Transfer from {account_labels[transfer.source_account]} — '
                f'{transfer.description}'
            ),
            reference=transfer.reference,
            recorded_by=actor,
            inflow=transfer.amount,
            entry_type='Transfer',
        )

    for entry in BranchBalanceSheetEntry.objects.filter(
        branch__in=statement_branches,
        as_of_date__range=(date_from, date_to),
    ).select_related('branch', 'entered_by'):
        append_row(
            branch=entry.branch,
            transaction_date=entry.as_of_date,
            account=(
                'Bank' if entry.category == 'bank_deposit'
                else entry.get_category_display()
            ),
            description=f'{entry.account_name} balance',
            reference='',
            recorded_by=(
                entry.entered_by.get_full_name() or entry.entered_by.username
                if entry.entered_by_id else '—'
            ),
            balance=entry.amount,
            entry_type='Balance snapshot',
        )

    account_options = sorted(
        {row['account'] for row in rows},
        key=str.casefold,
    )
    selected_account = (
        'Bank' if bank_only else request.GET.get('account', '').strip()
    )
    if selected_account:
        rows = [row for row in rows if row['account'].casefold() == selected_account.casefold()]
    rows.sort(key=lambda row: (row['date'], row['branch'].name, row['description']), reverse=True)
    transaction_page = Paginator(rows, 50).get_page(request.GET.get('page'))
    filter_params = request.GET.copy()
    filter_params.pop('page', None)

    return render(request, 'documents/branch_account_statement.html', {
        'branches': branches,
        'selected_branch': selected_branch,
        'date_from': date_from,
        'date_to': date_to,
        'transactions': transaction_page,
        'selected_account': selected_account,
        'bank_only': bank_only,
        'account_options': account_options,
        'filter_query': filter_params.urlencode(),
        'total_inflow': sum((row['inflow'] for row in rows), Decimal('0')),
        'total_outflow': sum((row['outflow'] for row in rows), Decimal('0')),
    })


def _financial_report(request, report_view, balance_sheet_entry_form=None):
    today = timezone.localdate()
    month_start = date(today.year, today.month, 1)
    raw_start = request.GET.get('from', '').strip()
    raw_end = request.GET.get('to', '').strip()
    period = request.GET.get('period', 'this_month')
    period_options = [
        ('this_week', 'This week'),
        ('this_month', 'This month'),
    ]
    valid_periods = {value for value, label in period_options}
    if period not in valid_periods:
        period = 'this_month'

    custom_dates = bool(raw_start or raw_end)
    if custom_dates:
        try:
            date_from = date.fromisoformat(raw_start) if raw_start else month_start
            date_to = date.fromisoformat(raw_end) if raw_end else today
            period = 'custom'
        except ValueError:
            messages.error(request, 'Invalid report dates. Showing the current month instead.')
            date_from, date_to, period = month_start, today, 'this_month'
    elif period == 'this_week':
        date_from = today - timezone.timedelta(days=today.weekday())
        date_to = today
    else:
        date_from, date_to = month_start, today

    if date_from > date_to:
        messages.error(request, 'The start date must be on or before the end date.')
        date_from, date_to, period = month_start, today, 'this_month'

    zero = Decimal('0')

    def total_amount(queryset):
        return queryset.aggregate(total=Sum('amount'))['total'] or zero

    branches = company_branches_for_user(request.user).order_by('name')
    branch_count = branches.count()
    selected_branch = None
    requested_branch = request.GET.get('branch')
    if requested_branch:
        selected_branch = get_object_or_404(branches, pk=requested_branch)
    elif branch_count == 1:
        selected_branch = branches.first()
    has_branches = branch_count > 0

    payments = Payment.objects.filter(payment_date__range=(date_from, date_to))
    other_income = OtherIncome.objects.filter(income_date__range=(date_from, date_to))
    expenses = Expense.objects.filter(
        expense_date__range=(date_from, date_to),
        status='approved',
    )
    payments = scope_queryset(request.user, payments)
    other_income = scope_queryset(request.user, other_income)
    expenses = scope_queryset(request.user, expenses)
    if selected_branch:
        payments = payments.filter(branch=selected_branch)
        other_income = other_income.filter(branch=selected_branch)
        expenses = expenses.filter(branch=selected_branch)
    elif has_branches:
        payments = payments.filter(branch__external_reporting=False)
        other_income = other_income.filter(branch__external_reporting=False)
        expenses = expenses.filter(branch__external_reporting=False)

    summary_branches = branches
    if selected_branch:
        summary_branches = summary_branches.filter(pk=selected_branch.pk)
    daily_summaries = list(BranchDailySummary.objects.filter(
        branch__in=summary_branches,
        business_date__range=(date_from, date_to),
    ).select_related('branch', 'submitted_by', 'reviewed_by'))
    daily_ledger_entries = list(BranchDailyTransaction.objects.filter(
        branch__in=summary_branches,
        business_date__range=(date_from, date_to),
    ).select_related('branch', 'entered_by', 'expense_category'))
    ledger_dates = {
        (entry.branch_id, entry.business_date)
        for entry in daily_ledger_entries
    }
    summary_overrides = [
        (summary.branch_id, summary.business_date)
        for summary in daily_summaries
        if not summary.branch.external_reporting
    ]
    if summary_overrides:
        payment_overrides = Q()
        income_overrides = Q()
        expense_overrides = Q()
        for summary_branch_id, summary_date in summary_overrides:
            payment_overrides |= Q(branch_id=summary_branch_id, payment_date=summary_date)
            income_overrides |= Q(branch_id=summary_branch_id, income_date=summary_date)
            expense_overrides |= Q(branch_id=summary_branch_id, expense_date=summary_date)
        payments = payments.exclude(payment_overrides)
        other_income = other_income.exclude(income_overrides)
        expenses = expenses.exclude(expense_overrides)

    customer_receipts = total_amount(payments)
    capital_injections = total_amount(
        other_income.filter(category='capital_injection'),
    )
    other_receipts = total_amount(
        other_income.exclude(category='capital_injection'),
    )
    cash_outflow = total_amount(expenses)
    cash_inflow = customer_receipts + other_receipts + capital_injections
    net_cash_flow = cash_inflow - cash_outflow

    opening_cash = (
        total_amount(scope_queryset(request.user, Payment.objects.filter(payment_date__lt=date_from)))
        + total_amount(scope_queryset(request.user, OtherIncome.objects.filter(income_date__lt=date_from)))
        - total_amount(scope_queryset(request.user, Expense.objects.filter(
            expense_date__lt=date_from, status='approved',
        )))
    )
    closing_cash = opening_cash + net_cash_flow

    branch_comparison = branch_comparison_for_user(request.user, date_from, date_to)
    if selected_branch:
        branch_comparison = [
            row for row in branch_comparison if row['branch'].pk == selected_branch.pk
        ]
    if has_branches:
        customer_receipts = sum((row['customer_receipts'] for row in branch_comparison), zero)
        other_receipts = sum((row['other_receipts'] for row in branch_comparison), zero)
        capital_injections = sum(
            (row['capital_injections'] for row in branch_comparison), zero,
        )
        cash_inflow = customer_receipts + other_receipts + capital_injections
        cash_outflow = sum((row['outflow'] for row in branch_comparison), zero)
        net_cash_flow = cash_inflow - cash_outflow
        opening_cash = sum((row['opening_cash'] for row in branch_comparison), zero)
        closing_cash = sum((row['closing_cash'] for row in branch_comparison), zero)

    receivable_invoices = Invoice.objects.filter(
        date_issued__lte=date_to,
        document_type='invoice',
        status__in=('sent', 'partially_paid', 'paid', 'overdue'),
    )
    receivable_invoices = scope_queryset(request.user, receivable_invoices)
    if selected_branch:
        receivable_invoices = receivable_invoices.filter(branch=selected_branch)
    elif has_branches:
        receivable_invoices = receivable_invoices.filter(branch__in=branches)
    invoice_rows = list(receivable_invoices.values(
        'pk', 'branch_id', 'grand_total',
    ))
    invoiced_total = sum(
        (invoice['grand_total'] for invoice in invoice_rows), zero,
    )
    invoice_payments = Payment.objects.filter(
        invoice__in=receivable_invoices,
        payment_date__lte=date_to,
    )
    collected_total = total_amount(invoice_payments)
    paid_by_invoice = {
        row['invoice_id']: row['total'] or zero
        for row in invoice_payments.values('invoice_id').annotate(total=Sum('amount'))
    }
    accounts_receivable = sum(
        (
            max(invoice['grand_total'] - paid_by_invoice.get(invoice['pk'], zero), zero)
            for invoice in invoice_rows
        ),
        zero,
    )

    balance_sheet_branches = list(
        branches.filter(pk=selected_branch.pk) if selected_branch else branches
    )
    balance_sheet_assets = []
    balance_sheet_liabilities = []
    balance_sheet_equity = []
    cash_account_totals = {
        'cash_on_hand': zero,
        'bank_deposit': zero,
        'mobile_money': zero,
    }
    branch_prefix = (
        len(balance_sheet_branches) > 1
        and not selected_branch
    )
    account_labels = {
        'cash_on_hand': 'Cash at hand',
        'bank_deposit': 'Bank deposits',
        'mobile_money': 'Mobile money',
    }
    for branch in balance_sheet_branches:
        cash_accounts = branch_cash_account_balances(branch, date_to)
        for account, label in account_labels.items():
            amount = cash_accounts[account]
            cash_account_totals[account] += amount
            balance_sheet_assets.append({
                'account_name': (
                    f'{branch.name} — {label}' if branch_prefix else label
                ),
                'category': label,
                'amount': amount,
                'source': 'Recorded transactions',
            })
    if not balance_sheet_branches:
        cash_account_totals['cash_on_hand'] = closing_cash
        balance_sheet_assets.append({
            'account_name': 'Recorded cash and bank',
            'category': 'Cash and cash equivalents',
            'amount': closing_cash,
            'source': 'Recorded receipts less expenses',
        })

    balance_sheet_assets.append({
        'account_name': 'Accounts receivable',
        'category': 'Debtors',
        'amount': accounts_receivable,
        'source': 'Unpaid invoices',
    })

    work_in_progress_by_branch = {branch.pk: zero for branch in balance_sheet_branches}
    for line_item in JobCardLineItem.objects.filter(
        job_card__branch__in=balance_sheet_branches,
        job_card__status='in_progress',
        job_card__created_at__date__lte=date_to,
        status='not_handled',
    ).select_related('job_card'):
        work_in_progress_by_branch[line_item.job_card.branch_id] += (
            line_item.negotiated_price + line_item.vat_amount
        )
    work_in_progress = sum(work_in_progress_by_branch.values(), zero)
    balance_sheet_assets.append({
        'account_name': 'Work in progress (contract value estimate)',
        'category': 'Work in progress',
        'amount': work_in_progress,
        'source': 'Uncompleted services on in-progress jobs',
    })

    manual_entries = latest_balance_sheet_entries(
        balance_sheet_branches, date_to,
    )
    automatic_cash_categories = {'cash_on_hand', 'bank_deposit', 'mobile_money'}
    for entry in manual_entries:
        if entry.category in automatic_cash_categories:
            continue
        item = {
            'account_name': (
                f'{entry.branch.name} — {entry.account_name}'
                if branch_prefix else entry.account_name
            ),
            'category': entry.get_category_display(),
            'amount': entry.amount,
            'source': 'Entered balance',
        }
        account_type = entry.account_type
        if account_type == 'asset':
            balance_sheet_assets.append(item)
        elif account_type == 'liability':
            balance_sheet_liabilities.append(item)
        else:
            balance_sheet_equity.append(item)

    lifetime_injections = zero
    lifetime_drawings = zero
    accumulated_operating_surplus = zero
    for branch in balance_sheet_branches:
        lifetime_summary = branch_cash_summary(branch, date.min, date_to)
        lifetime_injections += lifetime_summary['capital_injections']
        lifetime_drawings += lifetime_summary['drawings']
        accumulated_operating_surplus += lifetime_summary['operating_profit']
    if lifetime_injections:
        balance_sheet_equity.append({
            'account_name': 'Cumulative capital injections',
            'category': 'Capital',
            'amount': lifetime_injections,
            'source': 'Recorded capital injections',
        })
    if lifetime_drawings:
        balance_sheet_equity.append({
            'account_name': 'Cumulative drawings',
            'category': 'Drawings',
            'amount': -lifetime_drawings,
            'source': 'Recorded drawings',
        })
    if accumulated_operating_surplus:
        balance_sheet_equity.append({
            'account_name': 'Accumulated operating surplus (cash basis)',
            'category': 'Retained earnings',
            'amount': accumulated_operating_surplus,
            'source': 'Recorded receipts less expenses',
        })

    total_assets = sum(
        (item['amount'] for item in balance_sheet_assets), zero,
    )
    total_liabilities = sum(
        (item['amount'] for item in balance_sheet_liabilities), zero,
    )
    total_equity = sum(
        (item['amount'] for item in balance_sheet_equity), zero,
    )
    balance_difference = total_assets - total_liabilities - total_equity

    report_services = scope_queryset(
        request.user,
        ServiceType.objects.filter(is_active=True),
        branch_path='branches',
    ).distinct()
    if selected_branch:
        report_services = report_services.filter(branches=selected_branch)
    report_services = list(report_services.order_by('name'))
    selected_service_id = request.GET.get('service', '').strip()
    selected_service = next(
        (service for service in report_services if str(service.pk) == selected_service_id),
        None,
    )
    if selected_service_id and not selected_service:
        messages.error(request, 'The selected service is not available in this workspace.')
        selected_service_id = ''

    category_choices = [
        (f'expense:{category.pk}', f'Expense: {category.name}')
        for category in ExpenseCategory.objects.filter(is_active=True).order_by('name')
    ]
    category_choices.extend(
        (
            f'income:{value}',
            f'Capital injection: {label}'
            if value == 'capital_injection' else f'Other income: {label}',
        )
        for value, label in OtherIncome.CATEGORY
    )
    category_choices.extend(
        (f'ledger:{value}', f'Ledger: {label}')
        for value, label in BranchDailyTransaction.CATEGORY
    )
    service_categories = dict(ServiceType.CATEGORY)
    service_categories.update({
        service.category: service.get_category_display()
        for service in report_services
    })
    category_choices.extend(
        (f'service:{value}', f'Service: {label}')
        for value, label in sorted(service_categories.items(), key=lambda item: item[1].casefold())
    )
    category_choices.append(('payment:uncategorized', 'Customer payment: no service'))
    category_choices.append(('expense:uncategorized', 'Expense: no category'))
    category_choices.append(('credit:receivable', 'Credit sale: receivable'))
    category_choices.append(('summary', 'Daily summary'))
    valid_categories = {value for value, label in category_choices}
    selected_category = request.GET.get('category', '').strip()
    if selected_category and selected_category not in valid_categories:
        messages.error(request, 'The selected category is not available in this report.')
        selected_category = ''

    method_choices = []
    method_values = set()
    for value, label in (
        Payment.METHOD + Expense.METHOD + BranchDailyTransaction.ACCOUNT
        + [
            ('external_system', 'External system'),
            ('credit', 'Credit'),
            ('internal_transfer', 'Internal transfer'),
        ]
    ):
        if value not in method_values:
            method_values.add(value)
            method_choices.append((value, label))
    selected_method = request.GET.get('method', '').strip()
    if selected_method and selected_method not in method_values:
        messages.error(request, 'The selected payment method is not available in this report.')
        selected_method = ''

    record_type_choices = [
        ('payment', 'Customer payment'),
        ('credit', 'Credit sale'),
        ('income', 'Other income'),
        ('capital_injection', 'Capital injection'),
        ('expense', 'Approved expense'),
        ('drawing', 'Owner drawing'),
        ('transfer', 'Account transfer'),
        ('ledger', 'Daily ledger'),
        ('summary', 'Daily summary'),
    ]
    selected_record_type = request.GET.get('record_type', '').strip()
    if selected_record_type and selected_record_type not in {
        value for value, label in record_type_choices
    }:
        messages.error(request, 'The selected record type is not available in this report.')
        selected_record_type = ''

    transactions = []

    def user_label(user):
        if not user:
            return '—'
        return user.get_full_name() or user.username

    payment_rows = payments.select_related(
        'invoice__client', 'invoice__job_card', 'client', 'received_by',
        'service_type',
    ).prefetch_related('invoice__job_card__line_items__service_type')
    for payment in payment_rows:
        if payment.invoice_id:
            customer = payment.client.get_display_name() if payment.client_id else 'Customer'
            description = f'{payment.invoice.invoice_number} — {customer}'
        else:
            description = payment.client.get_display_name() if payment.client_id else 'Direct payment'
        payment_services = {}
        if payment.service_type_id:
            payment_services[payment.service_type_id] = payment.service_type
        if payment.invoice_id and payment.invoice.job_card_id:
            payment_services.update({
                line.service_type_id: line.service_type
                for line in payment.invoice.job_card.line_items.all()
                if line.service_type_id
            })
        payment_services = list(payment_services.values())
        transactions.append({
            'date': payment.payment_date,
            'id': payment.pk,
            'type': 'Customer payment',
            'type_key': 'payment',
            'description': description,
            'method': payment.get_method_display(),
            'method_key': payment.method,
            'reference': payment.reference or '—',
            'recorded_by': user_label(payment.received_by),
            'approved_by': '—',
            'inflow': payment.amount,
            'outflow': zero,
            'service_ids': [service.pk for service in payment_services],
            'service_names': [service.name for service in payment_services],
            'category_keys': (
                [f'service:{service.category}' for service in payment_services]
                if payment_services else ['payment:uncategorized']
            ),
        })

    credit_invoices = scope_queryset(
        request.user,
        Invoice.objects.filter(
            is_credit_sale=True,
            date_issued__range=(date_from, date_to),
        ).select_related('client', 'service_type', 'created_by'),
    )
    if selected_branch:
        credit_invoices = credit_invoices.filter(branch=selected_branch)
    elif has_branches:
        credit_invoices = credit_invoices.filter(branch__in=branches)
    for invoice in credit_invoices:
        service_ids = [invoice.service_type_id] if invoice.service_type_id else []
        service_names = [invoice.service_type.name] if invoice.service_type_id else []
        transactions.append({
            'date': invoice.date_issued,
            'id': invoice.pk,
            'type': 'Credit sale',
            'type_key': 'credit',
            'description': (
                f'{invoice.invoice_number} — {invoice.client.get_display_name()}'
            ),
            'method': 'Credit',
            'method_key': 'credit',
            'reference': '—',
            'recorded_by': user_label(invoice.created_by),
            'approved_by': '—',
            'inflow': zero,
            'outflow': zero,
            'service_ids': service_ids,
            'service_names': service_names,
            'category_keys': (
                [f'service:{invoice.service_type.category}', 'credit:receivable']
                if invoice.service_type_id else ['credit:receivable']
            ),
        })

    for income in other_income.select_related('recorded_by'):
        income_type = (
            'Capital injection'
            if income.category == 'capital_injection'
            else 'Other income'
        )
        transactions.append({
            'date': income.income_date,
            'id': income.pk,
            'type': income_type,
            'type_key': (
                'capital_injection'
                if income.category == 'capital_injection'
                else 'income'
            ),
            'description': f'{income.source_name} — {income.get_category_display()}',
            'method': income.get_collection_method_display(),
            'method_key': income.collection_method,
            'reference': income.reference or '—',
            'recorded_by': user_label(income.recorded_by),
            'approved_by': '—',
            'inflow': income.amount,
            'outflow': zero,
            'service_ids': [],
            'service_names': [],
            'category_keys': [f'income:{income.category}'],
        })

    for expense in expenses.select_related('category', 'paid_by', 'created_by', 'approved_by'):
        description = expense.description
        if expense.category_id:
            description = f'{expense.category.name} — {description}'
        transactions.append({
            'date': expense.expense_date,
            'id': expense.pk,
            'type': (
                'Owner drawing'
                if expense.category and expense.category.name.casefold() == 'drawing'
                else 'Approved expense'
            ),
            'type_key': 'expense',
            'record_type_keys': (
                ['expense', 'drawing']
                if expense.category and expense.category.name.casefold() == 'drawing'
                else ['expense']
            ),
            'description': description,
            'method': expense.get_payment_method_display(),
            'method_key': expense.payment_method,
            'reference': expense.reference or '—',
            'recorded_by': user_label(expense.paid_by or expense.created_by),
            'approved_by': user_label(expense.approved_by),
            'inflow': zero,
            'outflow': expense.amount,
            'service_ids': [],
            'service_names': [],
            'category_keys': [
                f'expense:{expense.category_id}' if expense.category_id else 'expense:uncategorized',
            ],
        })

    for entry in daily_ledger_entries:
        entry_type_key = 'ledger'
        entry_record_types = ['ledger']
        if entry.category == 'capital_injection':
            entry_type_key = 'capital_injection'
            entry_record_types.append('capital_injection')
        elif entry.category == 'drawing':
            entry_type_key = 'drawing'
            entry_record_types.append('drawing')
        transactions.append({
            'date': entry.business_date,
            'id': entry.pk,
            'type': entry.display_category,
            'type_key': entry_type_key,
            'record_type_keys': entry_record_types,
            'description': f'{entry.branch.name} — {entry.description}',
            'method': entry.get_account_display(),
            'method_key': entry.account,
            'reference': entry.reference or '—',
            'recorded_by': user_label(entry.entered_by),
            'approved_by': '—',
            'inflow': entry.amount if entry.direction == 'inflow' else zero,
            'outflow': entry.amount if entry.direction == 'outflow' else zero,
            'service_ids': [],
            'service_names': [],
            'category_keys': [f'ledger:{entry.category}'],
        })

    transfer_branches = branches
    if selected_branch:
        transfer_branches = transfer_branches.filter(pk=selected_branch.pk)
    account_labels = dict(BranchAccountTransfer.ACCOUNT_CHOICES)
    for transfer in BranchAccountTransfer.objects.filter(
        branch__in=transfer_branches,
        transfer_date__range=(date_from, date_to),
    ).select_related('branch', 'entered_by'):
        source_label = account_labels[transfer.source_account]
        destination_label = account_labels[transfer.destination_account]
        transfer_description = transfer.description
        transactions.extend([
            {
                'date': transfer.transfer_date,
                'id': transfer.pk,
                'type': 'Account transfer',
                'type_key': 'transfer',
                'record_type_keys': ['transfer'],
                'description': f'Transfer to {destination_label} — {transfer_description}',
                'method': 'Internal transfer',
                'method_key': 'internal_transfer',
                'reference': transfer.reference or '—',
                'recorded_by': user_label(transfer.entered_by),
                'approved_by': '—',
                'inflow': zero,
                'outflow': transfer.amount,
                'service_ids': [],
                'service_names': [],
                'category_keys': ['transfer'],
            },
            {
                'date': transfer.transfer_date,
                'id': transfer.pk,
                'type': 'Account transfer',
                'type_key': 'transfer',
                'record_type_keys': ['transfer'],
                'description': f'Transfer from {source_label} — {transfer_description}',
                'method': 'Internal transfer',
                'method_key': 'internal_transfer',
                'reference': transfer.reference or '—',
                'recorded_by': user_label(transfer.entered_by),
                'approved_by': '—',
                'inflow': transfer.amount,
                'outflow': zero,
                'service_ids': [],
                'service_names': [],
                'category_keys': ['transfer'],
            },
        ])

    capital_branches = branches
    if selected_branch:
        capital_branches = capital_branches.filter(pk=selected_branch.pk)
    capital_by_branch = {
        branch.pk: {
            'branch': branch,
            'injections': zero,
            'drawings': zero,
        }
        for branch in capital_branches
    }
    for item in OtherIncome.objects.filter(
        branch__in=capital_branches,
        category='capital_injection',
        income_date__range=(date_from, date_to),
    ).values('branch_id').annotate(total=Sum('amount')):
        capital_by_branch[item['branch_id']]['injections'] += item['total'] or zero
    for item in BranchDailyTransaction.objects.filter(
        branch__in=capital_branches,
        category='capital_injection',
        business_date__range=(date_from, date_to),
    ).values('branch_id').annotate(total=Sum('amount')):
        capital_by_branch[item['branch_id']]['injections'] += item['total'] or zero
    for item in Expense.objects.filter(
        branch__in=capital_branches,
        category__name__iexact='Drawing',
        status='approved',
        expense_date__range=(date_from, date_to),
    ).values('branch_id').annotate(total=Sum('amount')):
        capital_by_branch[item['branch_id']]['drawings'] += item['total'] or zero
    for item in BranchDailyTransaction.objects.filter(
        branch__in=capital_branches,
        category='drawing',
        business_date__range=(date_from, date_to),
    ).values('branch_id').annotate(total=Sum('amount')):
        capital_by_branch[item['branch_id']]['drawings'] += item['total'] or zero
    capital_drawings = sorted(
        capital_by_branch.values(),
        key=lambda item: item['branch'].name.casefold(),
    )
    capital_injection_total = sum(
        (item['injections'] for item in capital_drawings), zero,
    )
    drawing_total = sum((item['drawings'] for item in capital_drawings), zero)
    for item in capital_drawings:
        item['net'] = item['injections'] - item['drawings']
    capital_net_total = capital_injection_total - drawing_total

    for summary in daily_summaries:
        if summary.branch.external_reporting and (
            summary.branch_id, summary.business_date,
        ) in ledger_dates:
            continue
        transactions.append({
            'date': summary.business_date,
            'id': summary.pk,
            'type': 'Branch daily summary',
            'type_key': 'summary',
            'description': f'{summary.branch.name} end-of-day summary',
            'method': 'External system',
            'method_key': 'external_system',
            'reference': '—',
            'recorded_by': user_label(summary.submitted_by),
            'approved_by': user_label(summary.reviewed_by) if summary.reviewed_by_id else '—',
            'inflow': summary.cash_inflow,
            'outflow': summary.cash_outflow,
            'service_ids': [],
            'service_names': [],
            'category_keys': ['summary'],
        })

    if selected_category:
        transactions = [
            item for item in transactions
            if selected_category in item['category_keys']
        ]
    if selected_service:
        transactions = [
            item for item in transactions
            if selected_service.pk in item['service_ids']
        ]
    if selected_record_type:
        transactions = [
            item for item in transactions
            if selected_record_type in item.get(
                'record_type_keys', [item['type_key']],
            )
        ]
    if selected_method:
        transactions = [
            item for item in transactions
            if item['method_key'] == selected_method
        ]

    transactions.sort(key=lambda item: (item['date'], item['id'], item['type']), reverse=True)
    transaction_page = Paginator(transactions, 50).get_page(request.GET.get('page'))

    filter_params = request.GET.copy()
    filter_params.pop('page', None)
    if not selected_category:
        filter_params.pop('category', None)
    if not selected_service_id:
        filter_params.pop('service', None)
    if not selected_record_type:
        filter_params.pop('record_type', None)
    if not selected_method:
        filter_params.pop('method', None)

    report_scope_params = request.GET.copy()
    for key in list(report_scope_params.keys()):
        if key not in ('branch', 'period', 'from', 'to'):
            report_scope_params.pop(key, None)
    if selected_branch:
        report_scope_params['branch'] = str(selected_branch.pk)
    else:
        report_scope_params.pop('branch', None)
    report_scope_params['period'] = period
    if period == 'custom':
        report_scope_params['from'] = date_from.isoformat()
        report_scope_params['to'] = date_to.isoformat()
    else:
        report_scope_params.pop('from', None)
        report_scope_params.pop('to', None)

    template_name = (
        'documents/balance_sheet.html'
        if report_view == 'balance_sheet'
        else 'documents/financial_reports.html'
    )
    if report_view == 'balance_sheet' and balance_sheet_entry_form is None:
        balance_form_initial = {}
        if selected_branch:
            balance_form_initial['branch'] = selected_branch
        balance_sheet_entry_form = BranchBalanceSheetEntryForm(
            initial=balance_form_initial, branches=branches,
        )
    return render(request, template_name, {
        'date_from': date_from,
        'date_to': date_to,
        'period': period,
        'period_options': period_options,
        'customer_receipts': customer_receipts,
        'other_receipts': other_receipts,
        'capital_injections': capital_injections,
        'cash_inflow': cash_inflow,
        'cash_outflow': cash_outflow,
        'net_cash_flow': net_cash_flow,
        'opening_cash': opening_cash,
        'closing_cash': closing_cash,
        'invoiced_total': invoiced_total,
        'collected_total': collected_total,
        'accounts_receivable': accounts_receivable,
        'tracked_assets': total_assets,
        'balance_sheet_assets': balance_sheet_assets,
        'balance_sheet_liabilities': balance_sheet_liabilities,
        'balance_sheet_equity': balance_sheet_equity,
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'total_equity': total_equity,
        'balance_difference': balance_difference,
        'work_in_progress': work_in_progress,
        'cash_account_totals': cash_account_totals,
        'lifetime_injections': lifetime_injections,
        'lifetime_drawings': lifetime_drawings,
        'accumulated_operating_surplus': accumulated_operating_surplus,
        'transactions': transaction_page,
        'branches': branches,
        'selected_branch': selected_branch,
        'branch_comparison': branch_comparison,
        'capital_drawings': capital_drawings,
        'capital_injection_total': capital_injection_total,
        'drawing_total': drawing_total,
        'capital_net_total': capital_net_total,
        'balance_sheet_entry_form': balance_sheet_entry_form,
        'category_choices': category_choices,
        'selected_category': selected_category,
        'service_choices': report_services,
        'selected_service': selected_service,
        'method_choices': method_choices,
        'selected_method': selected_method,
        'record_type_choices': record_type_choices,
        'selected_record_type': selected_record_type,
        'filter_query': filter_params.urlencode(),
        'report_scope_query': report_scope_params.urlencode(),
        'report_view': report_view,
    })


@login_required
def audit_books(request):
    today = timezone.now().date()
    year = int(request.GET.get('year', today.year))
    years = list(range(today.year - 3, today.year + 2))

    total_revenue = scope_queryset(request.user, Invoice.objects.filter(date_issued__year=year)).aggregate(s=Sum('grand_total'))['s'] or 0
    total_collected = scope_queryset(request.user, Payment.objects.filter(payment_date__year=year)).aggregate(s=Sum('amount'))['s'] or 0
    outstanding = total_revenue - total_collected
    expenses = scope_queryset(request.user, Expense.objects.filter(expense_date__year=year, status='approved'))
    exp_by_cat = expenses.values('category__name').annotate(total=Sum('amount')).order_by('-total')
    total_expenses = expenses.aggregate(s=Sum('amount'))['s'] or 0
    gross_profit = total_collected - total_expenses

    return render(request, 'documents/audit_books.html', {
        'year': year, 'years': years, 'today': today,
        'total_revenue': total_revenue, 'total_collected': total_collected,
        'outstanding': outstanding, 'exp_by_cat': exp_by_cat,
        'total_expenses': total_expenses, 'gross_profit': gross_profit,
    })
