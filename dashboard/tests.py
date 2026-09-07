from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from core.models import User
from expenses.models import Expense, ExpenseCategory
from billing.models import OtherIncome


class DashboardViewTests(TestCase):
    def test_dashboard_adds_staff_completion_metrics(self):
        user = User.objects.create_user(
            username='dashboard-user',
            password='pass123',
            is_staff=True,
            is_active=True,
            is_active_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('staff_perf', response.context)
        self.assertTrue(response.context['staff_perf'])
        first_row = response.context['staff_perf'][0]
        self.assertIn('completion_pct', first_row)
        self.assertIn('completion_color', first_row)

    def test_dashboard_includes_running_capital_summary(self):
        user = User.objects.create_user(
            username='capital-user',
            password='pass123',
            is_staff=True,
            is_active=True,
            is_active_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('running_capital', response.context)
        self.assertIn('summary_cards', response.context)
        self.assertTrue(response.context['summary_cards'])

    def test_running_capital_uses_entry_time_and_shows_latest_five_entries(self):
        user = User.objects.create_user(
            username='capital-entry-time-user',
            password='pass1234',
            is_staff=True,
            is_active=True,
            is_active_staff=True,
        )
        self.client.force_login(user)
        category = ExpenseCategory.objects.create(name='Entry time test')
        now = timezone.now()

        Expense.objects.create(
            expense_date=now.date() - timedelta(days=90),
            category=category,
            description='Recent entered expense',
            amount=Decimal('100'),
            created_by=user,
        )
        old_expense = Expense.objects.create(
            expense_date=now.date(),
            category=category,
            description='Old entered expense',
            amount=Decimal('500'),
            created_by=user,
        )
        Expense.objects.filter(pk=old_expense.pk).update(created_at=now - timedelta(days=40))

        for index in range(6):
            OtherIncome.objects.create(
                source_name=f'Income {index}',
                amount=Decimal('10'),
                income_date=now.date() - timedelta(days=30),
                recorded_by=user,
            )

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.context['running_capital'], -40.0)
        recent = response.context['recent_cash_transactions']
        self.assertEqual(len(recent), 5)
        self.assertNotIn('Old entered expense', [item['title'] for item in recent])
        self.assertEqual(recent[0]['title'], 'Income 5')
