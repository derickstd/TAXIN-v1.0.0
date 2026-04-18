from django.db import models
from clients.models import Client
from services.models import JobCard
from core.models import User

class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name

class Expense(models.Model):
    METHOD = [('cash','Cash'),('mobile_money','Mobile Money'),('bank_transfer','Bank Transfer'),('petty_cash','Petty Cash')]
    STATUS = [('draft','Draft'),('submitted','Submitted'),('approved','Approved'),('rejected','Rejected'),('reimbursed','Reimbursed')]
    expense_date = models.DateField()
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True)
    description = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='paid_expenses')
    payment_method = models.CharField(max_length=20, choices=METHOD, default='cash')
    reference = models.CharField(max_length=100, blank=True)
    receipt_upload = models.FileField(upload_to='receipts/', blank=True, null=True)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    job_card = models.ForeignKey(JobCard, on_delete=models.SET_NULL, null=True, blank=True)
    is_billable = models.BooleanField(default=False)
    is_reimbursed = models.BooleanField(default=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_expenses')
    status = models.CharField(max_length=20, choices=STATUS, default='draft')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_expenses')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"{self.category} — UGX {self.amount:,.0f} on {self.expense_date}"
