from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.models import User
from expenses.models import Expense, ExpenseCategory, ExpenseApprovalSettings
from expenses.utils import should_require_approval


class ExpenseApprovalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='expense_user', password='pass123')
        self.category = ExpenseCategory.objects.create(name='Test Category', approval_required=True, is_active=True)
        self.settings = ExpenseApprovalSettings.objects.get_or_create(pk=1)[0]
        self.settings.auto_approve_under_amount = Decimal('0.00')
        self.settings.save()

    def test_should_require_approval_when_category_requires_it(self):
        self.assertTrue(should_require_approval(self.category))

    def test_should_not_require_approval_when_category_not_required(self):
        self.category.approval_required = False
        self.category.save()
        self.assertFalse(should_require_approval(self.category))

    def test_should_not_require_approval_for_small_expense_threshold(self):
        self.settings.auto_approve_under_amount = Decimal('5000.00')
        self.settings.save()
        expense = Expense.objects.create(
            expense_date=date.today(),
            category=self.category,
            description='Small expense',
            amount=Decimal('100.00'),
            paid_by=self.user,
            created_by=self.user,
            status='submitted',
        )
        self.assertFalse(should_require_approval(expense))

    def test_auto_approve_signal_on_submit(self):
        self.category.approval_required = False
        self.category.save()
        expense = Expense.objects.create(
            expense_date=date.today(),
            category=self.category,
            description='Signal expense',
            amount=Decimal('1000.00'),
            paid_by=self.user,
            created_by=self.user,
            status='submitted',
        )
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'approved')
