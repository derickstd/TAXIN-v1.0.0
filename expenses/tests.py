from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import Branch, Company, User
from expenses.models import Expense, ExpenseCategory, ExpenseApprovalSettings
from expenses.utils import should_require_approval
from expenses.views import ExpenseForm


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

    def test_superuser_can_approve_submitted_expense(self):
        superuser = User.objects.create_superuser(username='superadmin', password='pass123', email='super@example.com')
        expense = Expense.objects.create(
            expense_date=date.today(),
            category=self.category,
            description='Needs approval',
            amount=Decimal('1000.00'),
            paid_by=self.user,
            created_by=self.user,
            status='submitted',
        )
        self.client.force_login(superuser)
        response = self.client.post(f'/expenses/{expense.pk}/approve/')
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'approved')
        self.assertEqual(expense.approved_by, superuser)
        self.assertEqual(response.status_code, 302)

    def test_expense_list_uses_finance_breadcrumb_and_filter_card_actions(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('expenses:list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<li><a href="{reverse("billing:list")}">Finance</a></li>',
        )
        self.assertContains(response, '<li class="active" aria-current="page">Expenses</li>')
        self.assertNotContains(response, '<div class="page-header">')
        self.assertContains(response, 'Manage Categories')
        self.assertContains(response, 'Log Expense')
        html = response.content.decode()
        filter_card_start = html.index('aria-label="Expense search and filters"')
        filter_card_end = html.index('</section>', filter_card_start)
        actions_position = html.index('Manage Categories')
        self.assertLess(filter_card_start, actions_position)
        self.assertLess(actions_position, filter_card_end)

    def test_expense_entry_uses_the_users_branch_workspace(self):
        company = Company.objects.create(name='Expense Branch Co', slug='expense-branch')
        branch = Branch.objects.create(company=company, name='TAXMAN')
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])
        self.client.force_login(self.user)

        page = self.client.get(reverse('expenses:create'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="floating-expense-button"')
        self.assertContains(page, 'Record an expense for TAXMAN')

        response = self.client.post(reverse('expenses:create'), {
            'expense_date': date.today().isoformat(),
            'category': self.category.pk,
            'description': 'Branch workspace expense',
            'amount': '25000',
            'payment_method': 'cash',
        })

        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(description='Branch workspace expense')
        self.assertEqual(expense.branch, branch)

    def test_expense_categories_are_available_in_each_branch(self):
        company = Company.objects.create(name='Shared Categories Co', slug='shared-categories')
        branch = Branch.objects.create(company=company, name='PRIME FOCUS')
        user = User.objects.create_user(
            username='prime-focus-expense-user',
            password='pass1234',
            role='tax_officer',
            company=company,
            branch=branch,
        )

        form = ExpenseForm(user=user)

        self.assertIn(self.category, form.fields['category'].queryset)

    def test_invalid_expense_submission_shows_errors_and_preserves_input(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('expenses:create'), {
            'expense_date': date.today().isoformat(),
            'category': self.category.pk,
            'description': 'Expense that needs correction',
            'amount': 'not-a-number',
            'payment_method': 'cash',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please correct the highlighted fields before saving.')
        self.assertContains(response, 'Enter a number.')
        self.assertContains(
            response,
            'name="amount" value="not-a-number" class="form-control is-invalid" aria-invalid="true"',
        )
        self.assertContains(response, 'Expense that needs correction')
        self.assertFalse(Expense.objects.exists())

    def test_external_branch_expense_entry_opens_daily_total_form(self):
        company = Company.objects.create(name='External Expense Co', slug='external-expense')
        branch = Branch.objects.create(
            company=company, name='PRIME FOCUS', external_reporting=True,
        )
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])
        self.client.force_login(self.user)

        response = self.client.get(reverse('expenses:create'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            f"{reverse('documents:branch_daily_expense')}?branch={branch.pk}"
            '&open=transaction&direction=outflow&category=operating_expense',
        )
        self.assertFalse(Expense.objects.exists())
