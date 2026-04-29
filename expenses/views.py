from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count
from django.utils import timezone
from .models import Expense, ExpenseCategory
from django import forms
from clients.models import Client
from services.models import JobCard
from core.decorators import manager_or_admin_required
import datetime


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['expense_date', 'category', 'description', 'amount',
                  'payment_method', 'reference', 'receipt_upload',
                  'client', 'job_card', 'is_billable']
        widgets = {'expense_date': forms.DateInput(attrs={'type': 'date'}),
                   'description': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['expense_date'].initial = datetime.date.today()
        self.fields['category'].queryset = ExpenseCategory.objects.filter(is_active=True).order_by('name')
        self.fields['client'].queryset = Client.objects.order_by('full_name')
        self.fields['job_card'].queryset = JobCard.objects.order_by('-created_at')[:100]
        for f in ['client', 'job_card', 'reference', 'receipt_upload', 'is_billable']:
            self.fields[f].required = False


@login_required
def expense_list(request):
    expenses = Expense.objects.select_related('category', 'paid_by').order_by('-expense_date')
    cat = request.GET.get('category', '')
    if cat:
        expenses = expenses.filter(category_id=cat)
    total = expenses.aggregate(s=Sum('amount'))['s'] or 0
    approved_total = expenses.filter(status='approved').aggregate(s=Sum('amount'))['s'] or 0
    pending_count = expenses.filter(status='submitted').count()
    by_cat = expenses.values('category__name').annotate(total=Sum('amount')).order_by('-total')
    categories = ExpenseCategory.objects.filter(is_active=True).order_by('name')
    return render(request, 'expenses/expense_list.html', {
        'expenses': expenses, 'total': total, 'approved_total': approved_total,
        'pending_count': pending_count, 'by_cat': by_cat,
        'categories': categories, 'cat_filter': cat,
    })


@login_required
def expense_create(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            exp = form.save(commit=False)
            exp.paid_by = request.user
            exp.created_by = request.user
            exp.status = 'submitted'
            exp.save()
            messages.success(request, 'Expense logged and submitted for approval.')
            return redirect('expenses:list')
        messages.error(request, 'Please fix the errors below.')
    else:
        form = ExpenseForm()
    return render(request, 'expenses/expense_form.html', {
        'form': form,
        'today': datetime.date.today().isoformat(),
    })


@login_required
def approve_expense(request, pk):
    exp = get_object_or_404(Expense, pk=pk)
    if request.user.is_manager_or_admin():
        exp.status = 'approved'
        exp.approved_by = request.user
        exp.save()
        messages.success(request, f'Expense of UGX {exp.amount:,.0f} approved.')
    else:
        messages.error(request, 'Only managers can approve expenses.')
    return redirect('expenses:list')


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ['name', 'description', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


@manager_or_admin_required
def category_list(request):
    categories = ExpenseCategory.objects.all().order_by('name')
    return render(request, 'expenses/category_list.html', {'categories': categories})


@login_required
def category_create(request):
    if request.method == 'POST':
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            is_active = request.POST.get('is_active') == 'true'
            
            if not name:
                return JsonResponse({'success': False, 'error': 'Category name is required'})
            
            if ExpenseCategory.objects.filter(name=name).exists():
                return JsonResponse({'success': False, 'error': 'Category with this name already exists'})
            
            category = ExpenseCategory.objects.create(
                name=name,
                description=description,
                is_active=is_active
            )
            return JsonResponse({
                'success': True,
                'category': {
                    'id': category.pk,
                    'name': category.name,
                    'description': category.description
                }
            })
        
        # Regular form submission
        if not request.user.is_manager_or_admin():
            messages.error(request, 'Only managers can manage categories.')
            return redirect('expenses:list')
        
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Expense category created.')
            return redirect('expenses:category_list')
    else:
        if not request.user.is_manager_or_admin():
            messages.error(request, 'Only managers can manage categories.')
            return redirect('expenses:list')
        form = ExpenseCategoryForm()
    return render(request, 'expenses/category_form.html', {'form': form, 'action': 'Create'})


@manager_or_admin_required
def category_edit(request, pk):
    cat = get_object_or_404(ExpenseCategory, pk=pk)
    if request.method == 'POST':
        form = ExpenseCategoryForm(request.POST, instance=cat)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category updated.')
            return redirect('expenses:category_list')
    else:
        form = ExpenseCategoryForm(instance=cat)
    return render(request, 'expenses/category_form.html', {'form': form, 'action': 'Edit', 'category': cat})


@manager_or_admin_required
def category_delete(request, pk):
    cat = get_object_or_404(ExpenseCategory, pk=pk)
    if request.method == 'POST':
        cat.delete()
        messages.success(request, 'Category deleted.')
        return redirect('expenses:category_list')
    return render(request, 'expenses/category_confirm_delete.html', {'category': cat})
