"""
Views for duplicate client handling, transaction editing, and reporting.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q, Sum
from django.utils import timezone
from django.http import JsonResponse
from datetime import timedelta

from clients.models import Client
from core.models import (
    DuplicateClientSuggestion,
    TransactionEditLog,
    ReportingSettings,
    DuplicateTransactionAlert,
)
from core.transaction_forms import (
    DuplicateClientMergeForm,
    TransactionEditForm,
    ReportingSettingsForm,
    DuplicateDetectionFiltersForm,
    TransactionEditFieldsForm,
)
from core.duplicate_detection import find_duplicate_clients, merge_clients, check_duplicate_transaction
from core.reporting import (
    get_date_range_for_frequency,
    calculate_monthly_trends,
    generate_revenue_report,
    generate_collections_report,
    generate_outstanding_report,
    generate_compliance_report,
    generate_expenses_report,
    generate_performance_summary,
)


def is_superuser(user):
    """Check if user is a superuser."""
    return user.is_superuser or user.is_staff


@login_required
def duplicate_clients_list(request):
    """List potential duplicate clients for review and merging."""
    suggestions = DuplicateClientSuggestion.objects.select_related(
        'primary_client', 'duplicate_client', 'reviewed_by'
    ).all()
    
    # Filter form
    filter_form = DuplicateDetectionFiltersForm(request.GET or None)
    
    if filter_form.is_valid():
        statuses = filter_form.cleaned_data.get('status')
        if statuses:
            suggestions = suggestions.filter(status__in=statuses)
        
        min_similarity = filter_form.cleaned_data.get('min_similarity')
        if min_similarity:
            suggestions = suggestions.filter(similarity_score__gte=min_similarity)
        
        sort_by = filter_form.cleaned_data.get('sort_by')
        if sort_by:
            suggestions = suggestions.order_by(sort_by)
    else:
        suggestions = suggestions.filter(status='pending').order_by('-similarity_score')
    
    # Pagination
    from core.utils import paginate_queryset
    page_obj = paginate_queryset(request, suggestions, per_page=25)
    
    return render(request, 'core/duplicate_clients_list.html', {
        'page_obj': page_obj,
        'suggestions': page_obj,
        'filter_form': filter_form,
    })


@login_required
def duplicate_client_detail(request, pk):
    """View detail of a duplicate client suggestion."""
    suggestion = get_object_or_404(DuplicateClientSuggestion, pk=pk)
    
    if request.method == 'POST':
        form = DuplicateClientMergeForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            reason = form.cleaned_data['reason']
            
            if action == 'merge':
                merge_data = {
                    'keep_phone_from_duplicate': form.cleaned_data.get('keep_phone_from_duplicate'),
                    'keep_email_from_duplicate': form.cleaned_data.get('keep_email_from_duplicate'),
                    'keep_address_from_duplicate': form.cleaned_data.get('keep_address_from_duplicate'),
                    'keep_trading_name_from_duplicate': form.cleaned_data.get('keep_trading_name_from_duplicate'),
                }
                
                success, message, affected_count = merge_clients(
                    suggestion.primary_client,
                    suggestion.duplicate_client,
                    merge_data
                )
                
                if success:
                    suggestion.status = 'merged'
                    suggestion.reviewed_by = request.user
                    suggestion.reviewed_at = timezone.now()
                    suggestion.notes = reason
                    suggestion.save()
                    messages.success(request, message)
                else:
                    messages.error(request, message)
            
            elif action == 'cancel':
                suggestion.status = 'false_positive'
                suggestion.reviewed_by = request.user
                suggestion.reviewed_at = timezone.now()
                suggestion.notes = reason
                suggestion.save()
                messages.info(request, "Marked as false positive.")
            
            return redirect('duplicate_clients_list')
    else:
        form = DuplicateClientMergeForm()
    
    return render(request, 'core/duplicate_client_detail.html', {
        'suggestion': suggestion,
        'form': form,
        'primary_client': suggestion.primary_client,
        'duplicate_client': suggestion.duplicate_client,
    })


@login_required
@user_passes_test(is_superuser)
def transaction_edit_log(request):
    """View transaction edit logs (superuser only)."""
    edits = TransactionEditLog.objects.select_related('client', 'edited_by').all()
    
    # Filters
    transaction_type = request.GET.get('transaction_type')
    if transaction_type:
        edits = edits.filter(transaction_type=transaction_type)
    
    days = request.GET.get('days', 30)
    try:
        days = int(days)
        edits = edits.filter(edited_at__gte=timezone.now() - timedelta(days=days))
    except (ValueError, TypeError):
        pass
    
    from core.utils import paginate_queryset
    page_obj = paginate_queryset(request, edits.order_by('-edited_at'), per_page=50)
    
    return render(request, 'core/transaction_edit_log.html', {
        'page_obj': page_obj,
        'edits': page_obj,
        'transaction_types': TransactionEditLog.TRANSACTION_TYPES,
    })


@login_required
@user_passes_test(is_superuser)
def edit_transaction(request, transaction_type, transaction_id):
    """Edit a transaction (invoice, job card, etc.) - superuser only."""
    from billing.models import Invoice
    from services.models import JobCard
    from compliance.models import ComplianceDeadline
    
    # Get the transaction object
    transaction_obj = None
    if transaction_type == 'invoice':
        transaction_obj = get_object_or_404(Invoice, pk=transaction_id)
    elif transaction_type == 'job_card':
        transaction_obj = get_object_or_404(JobCard, pk=transaction_id)
    elif transaction_type == 'compliance_deadline':
        transaction_obj = get_object_or_404(ComplianceDeadline, pk=transaction_id)
    else:
        messages.error(request, "Invalid transaction type")
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = TransactionEditFieldsForm(transaction_obj, request.POST)
        if form.is_valid():
            reason = request.POST.get('reason', '')
            
            # Store old values
            old_values = {
                'status': getattr(transaction_obj, 'status', None),
                'due_date': str(getattr(transaction_obj, 'due_date', None)),
                'notes': getattr(transaction_obj, 'notes', ''),
            }
            
            # Update transaction
            for field, value in form.cleaned_data.items():
                if hasattr(transaction_obj, field):
                    setattr(transaction_obj, field, value)
            
            transaction_obj.save()
            
            # Log the edit
            TransactionEditLog.objects.create(
                transaction_type=transaction_type,
                transaction_id=transaction_id,
                transaction_code=getattr(transaction_obj, 'invoice_number', None) or \
                                 getattr(transaction_obj, 'job_number', None) or \
                                 f"{transaction_type}_{transaction_id}",
                client=transaction_obj.client if hasattr(transaction_obj, 'client') else \
                       transaction_obj.obligation.client if hasattr(transaction_obj, 'obligation') else None,
                old_values=old_values,
                new_values=form.cleaned_data,
                reason=reason,
                edited_by=request.user,
            )
            
            messages.success(request, f"{transaction_type.replace('_', ' ').title()} updated successfully.")
            return redirect('client_detail', pk=transaction_obj.client.pk if hasattr(transaction_obj, 'client') 
                          else transaction_obj.obligation.client.pk)
    else:
        form = TransactionEditFieldsForm(transaction_obj)
    
    return render(request, 'core/edit_transaction.html', {
        'form': form,
        'transaction_obj': transaction_obj,
        'transaction_type': transaction_type,
    })


@login_required
def duplicate_transactions_alerts(request):
    """View duplicate transaction alerts."""
    alerts = DuplicateTransactionAlert.objects.select_related('client', 'reviewed_by').all()
    
    status = request.GET.get('status')
    if status:
        alerts = alerts.filter(status=status)
    else:
        alerts = alerts.filter(status='pending')
    
    from core.utils import paginate_queryset
    page_obj = paginate_queryset(request, alerts.order_by('-created_at'), per_page=25)
    
    return render(request, 'core/duplicate_transactions_list.html', {
        'page_obj': page_obj,
        'alerts': page_obj,
    })


@login_required
def reporting_settings(request):
    """Manage reporting settings."""
    company = request.user.company
    if not company:
        messages.error(request, "You must be assigned to a company")
        return redirect('dashboard')
    
    settings_list = ReportingSettings.objects.filter(company=company)
    
    if request.method == 'POST' and 'create' in request.POST:
        form = ReportingSettingsForm(request.POST)
        if form.is_valid():
            setting = form.save(commit=False)
            setting.company = company
            setting.save()
            messages.success(request, "Reporting setting created successfully.")
            return redirect('reporting_settings')
    else:
        form = ReportingSettingsForm()
    
    return render(request, 'core/reporting_settings.html', {
        'settings_list': settings_list,
        'form': form,
    })


@login_required
def reporting_settings_edit(request, pk):
    """Edit a reporting setting."""
    setting = get_object_or_404(ReportingSettings, pk=pk, company=request.user.company)
    
    if request.method == 'POST':
        form = ReportingSettingsForm(request.POST, instance=setting)
        if form.is_valid():
            form.save()
            messages.success(request, "Reporting setting updated successfully.")
            return redirect('reporting_settings')
    else:
        form = ReportingSettingsForm(instance=setting)
    
    return render(request, 'core/reporting_settings_form.html', {
        'form': form,
        'setting': setting,
    })


@login_required
def generate_report(request, report_type):
    """Generate and display a report."""
    company = request.user.company
    if not company:
        messages.error(request, "You must be assigned to a company")
        return redirect('dashboard')
    
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    frequency = request.GET.get('frequency', 'monthly')
    
    # Parse dates
    from datetime import datetime
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date, end_date = get_date_range_for_frequency(frequency)
    else:
        start_date, end_date = get_date_range_for_frequency(frequency)
    
    report_data = {}
    
    if report_type == 'revenue':
        report_data = generate_revenue_report(company, start_date, end_date)
    elif report_type == 'collections':
        report_data = generate_collections_report(company, start_date, end_date)
    elif report_type == 'outstanding':
        report_data = generate_outstanding_report(company)
    elif report_type == 'compliance':
        report_data = generate_compliance_report(company)
    elif report_type == 'expenses':
        report_data = generate_expenses_report(company, start_date, end_date)
    elif report_type == 'performance':
        report_data = generate_performance_summary(company, start_date, end_date)
    else:
        messages.error(request, "Invalid report type")
        return redirect('dashboard')
    
    return render(request, 'core/report_view.html', {
        'report_type': report_type,
        'report_data': report_data,
        'start_date': start_date,
        'end_date': end_date,
    })
