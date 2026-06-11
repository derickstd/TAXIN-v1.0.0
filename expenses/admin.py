from django.contrib import admin
from .models import Expense, ExpenseCategory, ExpenseApprovalSettings


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'approval_required', 'is_active']
    list_filter = ['is_active', 'approval_required']
    search_fields = ['name', 'description']


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['expense_date', 'category', 'description', 'amount', 'status', 'paid_by', 'approved_by']
    list_filter = ['status', 'category', 'expense_date', 'payment_method']
    search_fields = ['description', 'reference', 'paid_by__username']
    readonly_fields = ['created_at', 'created_by']
    fieldsets = (
        ('Basic Info', {
            'fields': ('expense_date', 'category', 'description', 'amount', 'payment_method')
        }),
        ('Attachments & Billability', {
            'fields': ('receipt_upload', 'is_billable', 'reference')
        }),
        ('Related Records', {
            'fields': ('client', 'job_card')
        }),
        ('People', {
            'fields': ('paid_by', 'approved_by')
        }),
        ('Status & Audit', {
            'fields': ('status', 'is_reimbursed', 'created_by', 'created_at')
        }),
    )


@admin.register(ExpenseApprovalSettings)
class ExpenseApprovalSettingsAdmin(admin.ModelAdmin):
    list_display = ['auto_approve_under_amount', 'require_receipt_under_amount']
    fieldsets = (
        ('Auto-Approve Rules', {
            'fields': ('auto_approve_under_amount', 'auto_approve_expense_categories'),
            'description': 'Set amount thresholds and categories for auto-approval'
        }),
        ('Receipt Requirements', {
            'fields': ('require_receipt_under_amount',),
            'description': 'Require receipt upload for expenses above this amount'
        }),
    )
    
    def has_add_permission(self, request):
        # Limit to one settings record
        return not ExpenseApprovalSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Never allow deletion
        return False
